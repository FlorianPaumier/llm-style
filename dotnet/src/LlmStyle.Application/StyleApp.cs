using System.Text.RegularExpressions;
using LlmStyle.Application.Contracts;
namespace LlmStyle.Application;

public sealed partial class StyleApp(IStyleStore store,IPhotoStorage photos,IWeatherClient weather,ILlmClient llm,IJobQueue jobs) : IStyleApp
{
    private readonly object itemMutation=new();
    public IReadOnlyList<Persona> ListPersonas()=>store.ListPersonas();
    public Persona SavePersona(PersonaInput input,int? id=null,IReadOnlySet<string>? fields=null)=>store.SavePersona(input,id,fields);
    public void DeletePersona(int id)=>store.DeletePersona(id);
    public ItemPage ListItems(ItemQuery query)=>store.ListItems(query);
    public ItemView GetItem(int id)=>store.GetItem(id);
    public ItemView SaveItem(ItemInput input,int? id=null)
    {
        lock(itemMutation)
        {
            _=input.ToGarment(id ?? 0);
            if(input.PhotoToken is not null) _=DraftPhoto(input.PhotoToken);
            var item=store.SaveItem(input,id);
            if(input.PhotoToken is null) return item;
            try { return AttachPhoto(item.Id,input.PhotoToken); }
            catch { if(id is null) store.DeleteItem(item.Id); throw; }

        }
    }
    public void DeleteItem(int id) { lock(itemMutation) { var name=store.ImageName(id); store.DeleteItem(id); photos.Delete(name); } }
    public StyleSettings GetSettings()=>store.GetSettings();
    public StyleSettings UpdateSettings(IReadOnlyDictionary<string,string?> patch)=>store.UpdateSettings(patch);
    public IReadOnlyList<HistoryEntry> History(int limit=20,int? personaId=null)=>store.History(limit,personaId);
    public HistoryEntry GetHistory(int id)=>store.GetHistory(id);
    public WornResult MarkWorn(int id)=>store.MarkWorn(id);
    public PhotoFile ItemPhoto(int id)=>photos.Read(store.ImageName(id) ?? throw new StyleException(404,"This item has no photo."));
    [GeneratedRegex(@"^draft-[0-9a-f]{12}\.(jpg|jpeg|png|webp)$")]
    private static partial Regex DraftPattern();
    public PhotoFile DraftPhoto(string token)
    {
        if(!DraftPattern().IsMatch(token)) throw new ArgumentException("Photo token must be a server-issued draft token.");
        return photos.Read(token);
    }
    public ItemView AttachPhoto(int id,string token)
    {
        lock(itemMutation)
        {
            var previous=store.ImageName(id); _=DraftPhoto(token); var owned=photos.Claim(token,id);
            try { store.SetPhoto(id,owned); } catch { photos.Delete(owned); throw; }
            photos.Delete(previous); return store.GetItem(id);

        }
    }
    public ItemView UploadPhoto(int id,PhotoUpload upload) { _=store.GetItem(id); ValidateUpload(upload); return AttachPhoto(id,photos.SaveDraft(upload)); }
    public void RemovePhoto(int id) { lock(itemMutation) { var name=store.ImageName(id); store.SetPhoto(id,null); photos.Delete(name); } }
    public Task<Weather> WeatherAsync(CancellationToken cancellationToken=default)=>weather.CurrentAsync(store.GetSettings().City,cancellationToken);
    public JobStatus Job(string id)=>jobs.Get(id);
    public JobCreated RecommendJob(RecommendInput input)
    {
        ValidateRecommend(input);
        var snapshot=new RecommendInput { Mood=input.Mood,Occasion=input.Occasion,Activity=input.Activity,Count=input.Count,WeatherOverrideC=input.WeatherOverrideC,PersonaIds=input.PersonaIds?.ToList() };
        return jobs.Enqueue(async (_,ct)=>await RecommendAsync(snapshot,ct));
    }
    public JobCreated ClassifyPhotoJob(PhotoUpload upload)
    {
        ValidateUpload(upload);
        return jobs.Enqueue(async (_,ct)=>(await ClassifyAsync(upload,ct)).Select(d=>new BulkResult(true,upload.Filename,d)).ToArray());
    }
    public JobCreated ClassifyJob(IReadOnlyList<PhotoUpload> uploads)
    {
        if(uploads.Count is <1 or >20) throw new ArgumentException("Submit between 1 and 20 photos per request.");
        foreach(var upload in uploads) ValidateUpload(upload);
        return jobs.Enqueue(async (report,ct)=>
        {
            var results=new List<BulkResult>(); report(new(0,uploads.Count));
            for(var i=0;i<uploads.Count;i++)
            {
                ct.ThrowIfCancellationRequested(); var upload=uploads[i];
                try { results.AddRange((await ClassifyAsync(upload,ct)).Select(d=>new BulkResult(true,upload.Filename,d))); }
                catch(Exception e) when(e is not OperationCanceledException) { results.Add(new(false,upload.Filename,Error:e.Message)); }
                report(new(i+1,uploads.Count));
            }
            return results;
        });
    }
    private static void ValidateUpload(PhotoUpload upload)
    {
        var extension=Path.GetExtension(upload.Filename).ToLowerInvariant();
        if(extension is not (".jpg" or ".jpeg" or ".png" or ".webp") || upload.Bytes.Length==0) throw new ArgumentException("Upload a non-empty JPG, PNG or WebP image.");
        if(upload.Bytes.Length>10*1024*1024) throw new StyleException(413,"Photo must be under 10 MB.");
    }
}
