using System.Text.Json.Serialization;
using LlmStyle.Domain.Wardrobes;

namespace LlmStyle.Application.Contracts;

public sealed record Persona(int Id, string Name, string? Description = null, string Gender = "unspecified");
[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed class PersonaInput
{
    public string? Name { get; set; }
    public string? Description { get; set; }
    public string? Gender { get; set; }
}
[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed class ItemInput
{
    public string Name { get; set; } = "";
    public string Category { get; set; } = "";
    public string? Type { get; set; }
    public string? Color { get; set; }
    public int Warmth { get; set; }
    public int Formality { get; set; }
    public string? StyleTags { get; set; }
    public string? Notes { get; set; }
    public string? PhotoToken { get; set; }
    public int? PersonaId { get; set; }

    public Garment ToGarment(int id = 0)
    {
        var garment = new Garment(id, Name, Category, Warmth, Formality, Color, StyleTags, Notes);
        if (Type is not null && Type != garment.Type) throw new ArgumentException("Category and type do not match.");
        return garment;
    }
}
public sealed record ItemView(int Id, string Name, string Category, string Type, string? Color,
    int Warmth, int Formality, string? StyleTags, string? Notes, int TimesWorn, int PersonaId, bool HasPhoto, string? PhotoUrl)
{
    public Garment ToGarment() => new(Id, Name, Category, Warmth, Formality, Color, StyleTags, Notes);
    public ItemInput ToInput() => new() { Name = Name, Category = Category, Type = Type, Color = Color, Warmth = Warmth,
        Formality = Formality, StyleTags = StyleTags, Notes = Notes, PersonaId = PersonaId };
}
public sealed record ItemQuery(int Page = 1, int PageSize = 50, int? PersonaId = null, string? Type = null,
    int? Warmth = null, int? Formality = null, string? Q = null, string? Sort = null, string Order = "asc");
public sealed record ItemPage(IReadOnlyList<ItemView> Items, int Total, int Page, int PageSize, int Pages);
public sealed record StyleSettings(string City = "Paris", string Model = "dolphin-mistral:7b",
    string OllamaUrl = "http://localhost:11434", string VisionModel = "gemma3:4b");
public sealed record Weather(string City, double TemperatureC, double ApparentTemperatureC, double PrecipitationMm,
    double WindSpeedKmh, int WeatherCode, string FetchedAt);
[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
public sealed class RecommendInput
{
    public string Mood { get; set; } = "";
    public string Occasion { get; set; } = "casual";
    public string? Activity { get; set; }
    public double? WeatherOverrideC { get; set; }
    public List<int>? PersonaIds { get; set; }
    public int Count { get; set; } = 1;
}
public sealed record OutfitItem(string Slot, ItemView Item);
public sealed record PersonaOutfit(int PersonaId, string PersonaName, string Title, IReadOnlyList<OutfitItem> Outfit,
    string Rationale, string Source, IReadOnlyList<string> Gaps, int? HistoryId, int Option);
public sealed record Recommendation(string Title, IReadOnlyList<OutfitItem> Outfit, string Rationale, string Source,
    IReadOnlyList<string> Gaps, Weather Weather, int? HistoryId, IReadOnlyList<PersonaOutfit> Outfits);
public sealed record HistoryEntry(int Id, string CreatedAt, string Mood, string Occasion, Weather? Weather,
    IReadOnlyList<ItemView> Items, string? Rationale, string? Source, string? WornAt, int PersonaId);
public sealed record WornResult(int HistoryId, bool AlreadyWorn, IReadOnlyList<int> ItemIds);
public sealed record PhotoUpload(string Filename, byte[] Bytes);
public sealed record PhotoFile(byte[] Bytes, string ContentType)
{
    public string DataUrl => $"data:{ContentType};base64,{Convert.ToBase64String(Bytes)}";
}
public sealed record DraftItem(string Name, string Category, string Type, string? Color, int Warmth,
    int Formality, string? StyleTags, string PhotoToken)
{
    public ItemInput ToInput(int personaId) => new() { Name = Name, Category = Category, Type = Type, Color = Color,
        Warmth = Warmth, Formality = Formality, StyleTags = StyleTags, PhotoToken = PhotoToken, PersonaId = personaId };
}
public sealed record BulkResult(bool Ok, string Filename, DraftItem? Draft = null, string? Error = null);
public sealed record JobCreated(string JobId, string StatusUrl);
public sealed record JobProgress(int Done, int Total);
public sealed record JobStatus(string JobId, string Status, object? Result = null, string? Error = null, JobProgress? Progress = null);
public sealed record ChatMessage(string Role, string Content, string[]? Images = null);
public sealed class StyleException(int statusCode, string message) : Exception(message)
{
    public int StatusCode { get; } = statusCode;
}
