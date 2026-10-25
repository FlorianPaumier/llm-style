using System.Text.Json;
using LlmStyle.Application.Contracts;
using LlmStyle.Domain.Wardrobes;
namespace LlmStyle.Infrastructure.Storage;

public sealed partial class SqliteStyleStore
{
    private static readonly JsonSerializerOptions JsonOptions=new() { PropertyNamingPolicy=JsonNamingPolicy.SnakeCaseLower,PropertyNameCaseInsensitive=true };
    public StyleSettings GetSettings() { using var c=Open(); return ReadSettings(c); }
    private StyleSettings ReadSettings(Microsoft.Data.Sqlite.SqliteConnection c)
    {
        var r=Rows(c,"SELECT * FROM settings WHERE id=1")[0];
        string Effective(string key,string fallback) => string.IsNullOrEmpty(Text(r,key)) ? fallback : Text(r,key)!;
        return new(Effective("city",defaults.City),Effective("model",defaults.Model),Effective("ollama_url",defaults.OllamaUrl),Effective("vision_model",defaults.VisionModel));
    }
    public StyleSettings UpdateSettings(IReadOnlyDictionary<string,string?> patch)
    {
        using var c=Open(); using var transaction=c.BeginTransaction(deferred:false);
        var current=ReadSettings(c); var allowed=new[] { "city","model","vision_model","ollama_url" };
        if (patch.Keys.Any(k=>!allowed.Contains(k))) throw new ArgumentException("Unknown settings field.");
        string Merge(string field,string value,string fallback)
        {
            if (!patch.TryGetValue(field,out var incoming)) return value;
            Garment.CheckText(incoming,field=="ollama_url"?300:100,field);
            return string.IsNullOrWhiteSpace(incoming)?fallback:incoming.Trim();
        }
        var next=new StyleSettings(Merge("city",current.City,defaults.City),Merge("model",current.Model,defaults.Model),Merge("ollama_url",current.OllamaUrl,defaults.OllamaUrl),Merge("vision_model",current.VisionModel,defaults.VisionModel));
        if (!Uri.TryCreate(next.OllamaUrl,UriKind.Absolute,out var uri) || uri.Scheme is not ("http" or "https")) throw new ArgumentException("Ollama URL must be HTTP or HTTPS.");
        Execute(c,"UPDATE settings SET city=$0,model=$1,ollama_url=$2,vision_model=$3 WHERE id=1",next.City,next.Model,next.OllamaUrl,next.VisionModel); transaction.Commit(); return next;
    }
    private HistoryEntry Entry(Dictionary<string,object?> r)
    {
        var ids=JsonSerializer.Deserialize<int[]>(Text(r,"item_ids_json")!)!; var items=new List<ItemView>();
        foreach (var id in ids) { try { items.Add(GetItem(id)); } catch (StyleException e) when(e.StatusCode==404) { } }
        Weather? weather=null; try { if(Text(r,"weather_json") is {} json) weather=JsonSerializer.Deserialize<Weather>(json,JsonOptions); } catch(JsonException) { }
        return new(Number(r,"id"),Text(r,"created_at")!,Text(r,"mood")!,Text(r,"occasion")!,weather,items,Text(r,"rationale"),Text(r,"source"),Text(r,"worn_at"),Number(r,"persona_id"));
    }
    public IReadOnlyList<HistoryEntry> History(int limit=20,int? personaId=null)
    {
        if (limit is <1 or >100 || personaId is <=0) throw new ArgumentException("Invalid history filter.");
        using var c=Open(); return (personaId is null ? Rows(c,"SELECT * FROM outfit_history ORDER BY id DESC LIMIT $0",limit) : Rows(c,"SELECT * FROM outfit_history WHERE persona_id=$0 ORDER BY id DESC LIMIT $1",personaId,limit)).Select(Entry).ToArray();
    }
    public HistoryEntry GetHistory(int id)
    { using var c=Open(); return Rows(c,"SELECT * FROM outfit_history WHERE id=$0",id).Select(Entry).FirstOrDefault() ?? throw new StyleException(404,"History entry not found."); }
    public int AddHistory(RecommendInput request,int personaId,Weather weather,IReadOnlyList<int> ids,string title,string rationale,string source)
    {
        using var c=Open(); Execute(c,"INSERT INTO outfit_history(mood,occasion,weather_json,item_ids_json,rationale,source,persona_id) VALUES($0,$1,$2,$3,$4,$5,$6)",request.Mood,request.Occasion,JsonSerializer.Serialize(weather,JsonOptions),JsonSerializer.Serialize(ids),rationale,source,personaId); return LastId(c);
    }
    public WornResult MarkWorn(int id)
    {
        using var c=Open(); using var transaction=c.BeginTransaction(deferred:false);
        var r=Rows(c,"SELECT * FROM outfit_history WHERE id=$0",id).FirstOrDefault() ?? throw new StyleException(404,"History entry not found.");
        var ids=JsonSerializer.Deserialize<int[]>(Text(r,"item_ids_json")!)!; var already=Text(r,"worn_at") is not null;
        if (!already)
        {
            Execute(c,"UPDATE outfit_history SET worn_at=$0 WHERE id=$1",DateTimeOffset.UtcNow.ToString("O"),id);
            foreach (var itemId in ids.Distinct()) Execute(c,"UPDATE items SET times_worn=times_worn+1 WHERE id=$0",itemId);
        }
        transaction.Commit(); return new(id,already,ids);
    }
}
