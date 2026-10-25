using System.Text.Json;
using System.Text.Json.Serialization;
using LlmStyle.Application;
using LlmStyle.Application.Contracts;
using LlmStyle.Infrastructure.Photos;
namespace LlmStyle.Web.Endpoints;

public static class StyleApi
{
    private static readonly JsonSerializerOptions Options=new() { PropertyNamingPolicy=JsonNamingPolicy.SnakeCaseLower,UnmappedMemberHandling=JsonUnmappedMemberHandling.Disallow };
    private static T Read<T>(JsonElement body)
    {
        if(body.ValueKind!=JsonValueKind.Object) throw new ArgumentException("JSON body must be an object.");
        return body.Deserialize<T>(Options) ?? throw new ArgumentException("Request body is required.");
    }
    private static Dictionary<string,string?> Patch(JsonElement body)
    {
        if(body.ValueKind!=JsonValueKind.Object) throw new ArgumentException("JSON body must be an object.");
        return body.EnumerateObject().ToDictionary(p=>p.Name,p=>p.Value.ValueKind==JsonValueKind.Null?null:p.Value.ValueKind==JsonValueKind.String?p.Value.GetString():throw new ArgumentException("Patch values must be strings or null."));
    }
    private static int? Integer(HttpRequest request,string name,int? fallback=null)
        => request.Query.TryGetValue(name,out var text) ? int.TryParse(text,out var value)?value:throw new ArgumentException($"{name} must be an integer.") : fallback;
    private static string? Text(HttpRequest request,string name)=>request.Query.TryGetValue(name,out var text)?text.ToString():null;
    public static void MapStyleApi(this WebApplication app)
    {
        app.MapGet("/api/items",(HttpRequest r,IStyleApp s)=>s.ListItems(new(Integer(r,"page",1)!.Value,Integer(r,"page_size",50)!.Value,Integer(r,"persona_id"),Text(r,"type"),Integer(r,"warmth"),Integer(r,"formality"),Text(r,"q"),Text(r,"sort"),Text(r,"order")??"asc")));
        app.MapPost("/api/items",(JsonElement body,IStyleApp s)=>Results.Json(s.SaveItem(Read<ItemInput>(body)),statusCode:201));
        app.MapGet("/api/items/{id:int}",(int id,IStyleApp s)=>s.GetItem(id));
        app.MapPut("/api/items/{id:int}",(int id,JsonElement body,IStyleApp s)=>
        {
            var input=Read<ItemInput>(body);
            if(body.TryGetProperty("photo_token",out _)) throw new ArgumentException("Manage photos through the photo endpoint.");
            return s.SaveItem(input,id);
        });
        app.MapDelete("/api/items/{id:int}",(int id,IStyleApp s)=>{s.DeleteItem(id);return Results.NoContent();});
        app.MapGet("/api/items/{id:int}/photo",(int id,IStyleApp s)=>File(s.ItemPhoto(id)));
        app.MapPost("/api/items/{id:int}/photo",(int id,JsonElement body,IStyleApp s)=>
        {
            var patch=Patch(body); if(patch.Count!=1 || !patch.TryGetValue("photo_token",out var token) || token is null) throw new ArgumentException("A photo_token is required.");
            return Results.Json(s.AttachPhoto(id,token),statusCode:201);
        });
        app.MapDelete("/api/items/{id:int}/photo",(int id,IStyleApp s)=>{s.RemovePhoto(id);return Results.NoContent();});
        app.MapGet("/api/personas",(IStyleApp s)=>s.ListPersonas());
        app.MapPost("/api/personas",(JsonElement body,IStyleApp s)=>Results.Json(s.SavePersona(Read<PersonaInput>(body)),statusCode:201));
        app.MapPut("/api/personas/{id:int}",(int id,JsonElement body,IStyleApp s)=>s.SavePersona(Read<PersonaInput>(body),id,body.EnumerateObject().Select(p=>p.Name).ToHashSet()));
        app.MapDelete("/api/personas/{id:int}",(int id,IStyleApp s)=>{s.DeletePersona(id);return Results.NoContent();});
        app.MapGet("/api/settings",(IStyleApp s)=>s.GetSettings());
        app.MapPut("/api/settings",(JsonElement body,IStyleApp s)=>s.UpdateSettings(Patch(body)));
        app.MapGet("/api/weather",async(IStyleApp s,CancellationToken ct)=>await s.WeatherAsync(ct));
        app.MapPost("/api/outfits/recommend",async(JsonElement body,IStyleApp s,CancellationToken ct)=>await s.RecommendAsync(Read<RecommendInput>(body),ct));
        app.MapPost("/api/outfits/recommend/async",(JsonElement body,IStyleApp s)=>Results.Json(s.RecommendJob(Read<RecommendInput>(body)),statusCode:202));
        app.MapGet("/api/jobs/{id}",(string id,IStyleApp s)=>s.Job(id));
        app.MapGet("/api/history",(HttpRequest r,IStyleApp s)=>s.History(Integer(r,"limit",20)!.Value,Integer(r,"persona_id")));
        app.MapGet("/api/history/{id:int}",(int id,IStyleApp s)=>s.GetHistory(id));
        app.MapPost("/api/history/{id:int}/worn",(int id,IStyleApp s)=>s.MarkWorn(id));
        app.MapGet("/api/classify/photo/{token}",(string token,IStyleApp s)=>File(s.DraftPhoto(token)));
        app.MapPost("/api/classify",async(HttpRequest r,IStyleApp s,CancellationToken ct)=>new {items=await s.ClassifyAsync((await Uploads(r,"photo",1,ct))[0],ct)});
        app.MapPost("/api/classify/async",async(HttpRequest r,IStyleApp s,CancellationToken ct)=>Results.Json(s.ClassifyPhotoJob((await Uploads(r,"photo",1,ct))[0]),statusCode:202));
        app.MapPost("/api/classify/bulk",async(HttpRequest r,IStyleApp s,CancellationToken ct)=>Results.Json(s.ClassifyJob(await Uploads(r,"photos",20,ct)),statusCode:202));
        app.MapPost("/api/items/from-photo",async(HttpRequest r,IStyleApp s,CancellationToken ct)=>
        {
            var uploads=await Uploads(r,"photo",1,ct); var form=await r.ReadFormAsync(ct);
            int? persona=form.TryGetValue("persona_id",out var value)?int.TryParse(value,out var id)?id:throw new ArgumentException("Invalid persona ID."):null;
            return Results.Json(new {items=await s.QuickAddAsync(uploads[0],persona,ct)},statusCode:201);
        });
        app.MapGet("/api/health",()=>new {status="ok",version="0.1.0"});
    }
    private static IResult File(PhotoFile photo)=>Results.File(photo.Bytes,photo.ContentType);
    private static async Task<IReadOnlyList<PhotoUpload>> Uploads(HttpRequest request,string field,int max,CancellationToken ct)
    {
        if(!request.HasFormContentType) throw new ArgumentException("Upload a multipart form.");
        var form=await request.ReadFormAsync(ct); var files=form.Files.GetFiles(field);
        if(files.Count<1 || files.Count>max) throw new ArgumentException($"Submit between 1 and {max} {field} file(s).");
        var uploads=new List<PhotoUpload>();
        foreach(var file in files)
        {
            if(file.Length>LocalPhotoStorage.MaxBytes) throw new StyleException(413,"Photo must be under 10 MB.");
            await using var stream=file.OpenReadStream(); using var output=new MemoryStream(); await stream.CopyToAsync(output,ct);
            var upload=new PhotoUpload(file.FileName,output.ToArray()); LocalPhotoStorage.Validate(upload); uploads.Add(upload);
        }
        return uploads;
    }
}
