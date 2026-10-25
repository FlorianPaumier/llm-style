using LlmStyle.Application.Contracts;

namespace LlmStyle.Application;

public interface IStyleStore
{
    IReadOnlyList<Persona> ListPersonas();
    Persona SavePersona(PersonaInput input, int? id = null, IReadOnlySet<string>? fields = null);
    void DeletePersona(int id);
    ItemPage ListItems(ItemQuery query);
    IReadOnlyList<ItemView> Wardrobe(int personaId);
    ItemView GetItem(int id);
    ItemView SaveItem(ItemInput input, int? id = null);
    void SetPhoto(int id, string? filename);
    string? ImageName(int id);
    void DeleteItem(int id);
    StyleSettings GetSettings();
    StyleSettings UpdateSettings(IReadOnlyDictionary<string, string?> patch);
    IReadOnlyList<HistoryEntry> History(int limit = 20, int? personaId = null);
    HistoryEntry GetHistory(int id);
    int AddHistory(RecommendInput request, int personaId, Weather weather, IReadOnlyList<int> ids, string title, string rationale, string source);
    WornResult MarkWorn(int id);
}
public interface IPhotoStorage
{
    string SaveDraft(PhotoUpload upload);
    string Claim(string token, int id);
    PhotoFile Read(string name);
    void Delete(string? name);
}
public interface IWeatherClient { Task<Weather> CurrentAsync(string city, CancellationToken cancellationToken = default); }
public interface ILlmClient
{
    Task<string> CompleteAsync(StyleSettings settings, IReadOnlyList<ChatMessage> messages,
        bool vision = false, CancellationToken cancellationToken = default);
}
public interface IJobQueue
{
    JobCreated Enqueue(Func<Action<JobProgress>, CancellationToken, Task<object>> work);
    JobStatus Get(string id);
}
public interface IStyleApp
{
    IReadOnlyList<Persona> ListPersonas();
    Persona SavePersona(PersonaInput input, int? id = null, IReadOnlySet<string>? fields = null);
    void DeletePersona(int id);
    ItemPage ListItems(ItemQuery query);
    ItemView GetItem(int id);
    ItemView SaveItem(ItemInput input, int? id = null);
    void DeleteItem(int id);
    StyleSettings GetSettings();
    StyleSettings UpdateSettings(IReadOnlyDictionary<string, string?> patch);
    IReadOnlyList<HistoryEntry> History(int limit = 20, int? personaId = null);
    HistoryEntry GetHistory(int id);
    WornResult MarkWorn(int id);
    PhotoFile ItemPhoto(int id);
    PhotoFile DraftPhoto(string token);
    ItemView AttachPhoto(int id, string token);
    ItemView UploadPhoto(int id, PhotoUpload upload);
    void RemovePhoto(int id);
    Task<Weather> WeatherAsync(CancellationToken cancellationToken = default);
    Task<Recommendation> RecommendAsync(RecommendInput input, CancellationToken cancellationToken = default);
    Task<IReadOnlyList<DraftItem>> ClassifyAsync(PhotoUpload upload, CancellationToken cancellationToken = default);
    Task<IReadOnlyList<ItemView>> QuickAddAsync(PhotoUpload upload, int? personaId, CancellationToken cancellationToken = default);
    JobCreated RecommendJob(RecommendInput input);
    JobCreated ClassifyJob(IReadOnlyList<PhotoUpload> uploads);
    JobCreated ClassifyPhotoJob(PhotoUpload upload);
    JobStatus Job(string id);
}

public sealed record InstallationInfo(bool IsDesktop,string PrimaryUrl,IReadOnlyList<string> LanUrls,string? QrSvgUrl);
public interface IInstallationInfo { InstallationInfo Get(string baseUri); }
