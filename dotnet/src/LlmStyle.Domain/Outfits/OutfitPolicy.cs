using LlmStyle.Domain.Wardrobes;
namespace LlmStyle.Domain.Outfits;

public static class OutfitPolicy
{
    public static readonly IReadOnlyDictionary<string,(int Low,int High,int Target)> Formality = new Dictionary<string,(int,int,int)>
    { ["gym"]=(1,3,1),["casual"]=(1,3,2),["work"]=(2,4,3),["smart"]=(3,5,4),["formal"]=(4,5,5) };
    public static (int Low,int High) WarmthBand(double temperature) => temperature switch { >=24=>(1,1),>=17=>(1,2),>=10=>(2,3),>=4=>(3,4),_=>(4,5) };
    public static CandidateSet Select(IEnumerable<Garment> wardrobe,double temperature,string occasion,int seed,string? activity=null)
    {
        if (!Formality.TryGetValue(occasion,out var formality)) throw new ArgumentException("Unknown occasion.");
        var items=wardrobe.ToArray(); var band=WarmthBand(temperature); var random=new Random(seed);
        var result=new CandidateSet(temperature,occasion);
        foreach (var slot in new[] { "top","bottom","shoes","outerwear","accessory" })
        {
            if (slot=="outerwear" && temperature>=14) continue;
            List<Garment> Match(int low,int high)=>items.Where(g=>g.Type==slot && g.Warmth>=low && g.Warmth<=high && g.Formality>=formality.Low && g.Formality<=formality.High).ToList();
            var matches=Match(band.Low,band.High);
            for (var step=1; matches.Count==0 && step<=4; step++)
            {
                matches=Match(Math.Max(1,band.Low-step),Math.Min(5,band.High+step));
                if(matches.Count>0) result.Gaps.Add($"No {slot} in the ideal warmth band for {temperature:0}°C; closest matches were relaxed in.");
            }
            var cap=slot is "outerwear" or "accessory" ? 4 : 8;
            result.Slots[slot]=matches.Count>cap ? matches.OrderBy(g=>g.Id).OrderBy(_=>random.Next()).Take(cap).ToList() : matches;
        }
        if(!string.IsNullOrWhiteSpace(activity) && !result.ByRole("layer_upper").Any())
            result.Slots["top"].AddRange(items.Where(g=>g.Role=="layer_upper" && g.Formality>=formality.Low && g.Formality<=formality.High).OrderBy(g=>Math.Abs(g.Warmth-(band.Low+band.High)/2d)).ThenBy(g=>g.Id).Take(2));
        if (!result.ByRole("primary_upper").Any() && !result.ByRole("one_piece").Any()) result.Gaps.Add("No primary top fits these conditions. Add a shirt, tee, sweater or one-piece; a cardigan is only a layer.");
        if (!result.ByRole("primary_lower").Any() && !result.ByRole("one_piece").Any()) result.Gaps.Add("No primary bottom fits these conditions. Add trousers, jeans, a skirt or shorts; tights are only an underlayer.");
        if (!result.ForSlot("shoes").Any()) result.Gaps.Add("No shoes fit these conditions. Add footwear or change the occasion.");
        return result;
    }
}
public sealed class CandidateSet(double temperature,string occasion)
{
    public Dictionary<string,List<Garment>> Slots { get; } = new();
    public List<string> Gaps { get; }=[];
    public double Temperature { get; }=temperature;
    public string Occasion { get; }=occasion;
    public IEnumerable<Garment> All => Slots.Values.SelectMany(x=>x);
    public IEnumerable<Garment> ByRole(string role)=>All.Where(g=>g.Role==role);
    public IEnumerable<Garment> ForSlot(string slot)=>Slots.GetValueOrDefault(slot) ?? [];
    public bool HasRequired=>ForSlot("shoes").Any() && (ByRole("one_piece").Any() || ByRole("primary_upper").Any() && ByRole("primary_lower").Any());
    public IReadOnlyList<Garment> Validate(IReadOnlyDictionary<string,int?> picks,IReadOnlyList<int> accessories)
    {
        Garment? Find(string key,IEnumerable<Garment> pool,bool required=false)
        {
            if (!picks.TryGetValue(key,out var id) || id is null) { if(required) throw new ArgumentException($"Missing {key}."); return null; }
            return pool.FirstOrDefault(g=>g.Id==id) ?? throw new ArgumentException($"ID {id} is not a valid {key} candidate.");
        }
        var chosen=new List<Garment>();
        var top=Find("top",ByRole("primary_upper").Concat(ByRole("one_piece")),true)!; chosen.Add(top);
        var onePiece=top.Role=="one_piece";
        var bottom=Find("bottom",ByRole("primary_lower"),!onePiece);
        if(onePiece && bottom is not null) throw new ArgumentException("A one-piece replaces top and bottom.");
        if(bottom is not null) chosen.Add(bottom);
        var layer=Find("layer",ByRole("layer_upper")); if(layer is not null) chosen.Add(layer);
        var under=Find("underlayer",ByRole("lower_underlayer"));
        if(under is not null)
        {
            if (!onePiece && bottom?.Category is not ("skirt" or "shorts")) throw new ArgumentException("Underlayers require a skirt, dress or shorts.");
            chosen.Add(under);
        }
        chosen.Add(Find("shoes",ForSlot("shoes"),true)!);
        var outer=Find("outerwear",ForSlot("outerwear")); if(outer is not null) chosen.Add(outer);
        if(accessories.Count>2 || accessories.Distinct().Count()!=accessories.Count) throw new ArgumentException("Choose at most two distinct accessories.");
        foreach(var id in accessories) chosen.Add(ForSlot("accessory").FirstOrDefault(g=>g.Id==id) ?? throw new ArgumentException("Unknown accessory candidate."));
        return chosen;
    }
    public IReadOnlyList<Garment> Fallback(IReadOnlySet<int> avoid)
    {
        var target=OutfitPolicy.Formality[Occasion].Target;
        Garment? Pick(IEnumerable<Garment> pool)=>pool.OrderBy(g=>avoid.Contains(g.Id)).ThenBy(g=>Math.Abs(g.Formality-target)).ThenBy(g=>g.Id).FirstOrDefault();
        var selected=new List<Garment>(); void Add(Garment? garment) { if(garment is not null) selected.Add(garment); }
        var top=ByRole("primary_lower").Any() ? Pick(ByRole("primary_upper")) ?? Pick(ByRole("one_piece")) : Pick(ByRole("one_piece"));
        Add(top); var bottom=top?.Role=="one_piece"?null:Pick(ByRole("primary_lower")); Add(bottom);
        if(top is not null) Add(Pick(ByRole("layer_upper")));
        if(top?.Role=="one_piece" || bottom?.Category is "skirt" or "shorts") Add(Pick(ByRole("lower_underlayer")));
        Add(Pick(ForSlot("shoes"))); Add(Pick(ForSlot("outerwear")));
        var band=OutfitPolicy.WarmthBand(Temperature); Add(Pick(ForSlot("accessory").Where(g=>g.Warmth>=band.Low && g.Warmth<=band.High)));
        return selected;
    }
}
