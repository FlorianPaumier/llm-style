using LlmStyle.Application.Contracts;
namespace LlmStyle.Infrastructure.Storage;

public sealed partial class SqliteStyleStore
{
    private static ItemView Item(Dictionary<string,object?> r) => new(Number(r,"id"),Text(r,"name")!,Text(r,"category")!,Text(r,"type")!,
        Text(r,"color"),Number(r,"warmth"),Number(r,"formality"),Text(r,"style_tags"),Text(r,"notes"),Number(r,"times_worn"),
        Number(r,"persona_id"),Text(r,"image_path") is not null,Text(r,"image_path") is not null ? $"/api/items/{Number(r,"id")}/photo" : null);
    public ItemView GetItem(int id)
    { using var c=Open(); return Rows(c,"SELECT * FROM items WHERE id=$0",id).Select(Item).FirstOrDefault() ?? throw new StyleException(404,"Item not found."); }
    public IReadOnlyList<ItemView> Wardrobe(int personaId)
    { using var c=Open(); return Rows(c,"SELECT * FROM items WHERE persona_id=$0 ORDER BY id",personaId).Select(Item).ToArray(); }
    public ItemPage ListItems(ItemQuery query)
    {
        if (query.Page<1 || query.Page>int.MaxValue/Math.Max(1,query.PageSize) || query.PageSize is <1 or >200 || query.PersonaId is <=0 || query.Q?.Length>100 || query.Warmth is <1 or >5 || query.Formality is <1 or >5) throw new ArgumentException("Invalid pagination or filter.");
        var columns=new Dictionary<string,string> { ["name"]="name COLLATE NOCASE",["type"]="type",["category"]="category COLLATE NOCASE",["color"]="color COLLATE NOCASE",["warmth"]="warmth",["formality"]="formality",["style_tags"]="style_tags COLLATE NOCASE" };
        if (query.Sort is not null && !columns.ContainsKey(query.Sort) || query.Order is not ("asc" or "desc")) throw new ArgumentException("Invalid sort order.");
        if (query.Type is not null && query.Type is not ("top" or "bottom" or "shoes" or "outerwear" or "accessory")) throw new ArgumentException("Invalid item type.");
        using var c=Open(); var values=new List<object?>(); var filters=new List<string>();
        void Filter(string column,object value) { filters.Add($"{column}=${values.Count}"); values.Add(value); }
        Filter("persona_id",query.PersonaId ?? ListPersonas()[0].Id);
        if (query.Type is not null) Filter("type",query.Type);
        if (query.Warmth is not null) Filter("warmth",query.Warmth);
        if (query.Formality is not null) Filter("formality",query.Formality);
        if (!string.IsNullOrEmpty(query.Q)) { var key=$"${values.Count}"; filters.Add($"(name LIKE {key} OR color LIKE {key} OR style_tags LIKE {key})"); values.Add($"%{query.Q}%"); }
        var where=" WHERE "+string.Join(" AND ",filters);
        var total=Number(Rows(c,"SELECT COUNT(*) AS n FROM items"+where,values.ToArray())[0],"n");
        var order=query.Sort is null ? "id" : columns[query.Sort]+" "+query.Order+",id";
        var limit=$"${values.Count}"; values.Add(query.PageSize); var offset=$"${values.Count}"; values.Add(checked((query.Page-1)*query.PageSize));
        var items=Rows(c,$"SELECT * FROM items{where} ORDER BY {order} LIMIT {limit} OFFSET {offset}",values.ToArray()).Select(Item).ToArray();
        return new(items,total,query.Page,query.PageSize,Math.Max(1,(int)Math.Ceiling((double)total/query.PageSize)));
    }
    public ItemView SaveItem(ItemInput input,int? id=null)
    {
        var garment=input.ToGarment(id ?? 0); using var c=Open(); using var transaction=c.BeginTransaction(deferred:false);
        var current=id is null ? null : GetItem(id.Value); var personaId=input.PersonaId ?? current?.PersonaId ?? ListPersonas()[0].Id;
        if (personaId<1) throw new ArgumentException("Invalid persona ID."); _=RequirePerson(c,personaId);
        object?[] values=[garment.Name,garment.Type,garment.Category,garment.Color,garment.Warmth,garment.Formality,garment.StyleTags,garment.Notes,personaId];
        if (id is null)
        {
            Execute(c,"INSERT INTO items(name,type,category,color,warmth,formality,style_tags,notes,persona_id) VALUES($0,$1,$2,$3,$4,$5,$6,$7,$8)",values); id=LastId(c);
        }
        else Execute(c,"UPDATE items SET name=$0,type=$1,category=$2,color=$3,warmth=$4,formality=$5,style_tags=$6,notes=$7,persona_id=$8 WHERE id=$9",[..values,id]);
        transaction.Commit(); return GetItem(id.Value);
    }
    public void SetPhoto(int id,string? filename) { _=GetItem(id); using var c=Open(); Execute(c,"UPDATE items SET image_path=$0 WHERE id=$1",filename,id); }
    public string? ImageName(int id) { _=GetItem(id); using var c=Open(); return Text(Rows(c,"SELECT image_path FROM items WHERE id=$0",id)[0],"image_path"); }
    public void DeleteItem(int id) { _=GetItem(id); using var c=Open(); Execute(c,"DELETE FROM items WHERE id=$0",id); }
}
