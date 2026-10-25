using System.Text;
namespace LlmStyle.Domain.Wardrobes;

public sealed record Garment
{
    public int Id { get; }
    public string Name { get; }
    public string Category { get; }
    public string Type => GarmentCatalog.Categories[Category].Slot;
    public string Role => GarmentCatalog.Categories[Category].Role;
    public int Warmth { get; }
    public int Formality { get; }
    public string? Color { get; }
    public string? StyleTags { get; }
    public string? Notes { get; }

    public Garment(int id, string name, string category, int warmth, int formality,
        string? color = null, string? styleTags = null, string? notes = null)
    {
        CheckText(name, 100, "name", required: true);
        CheckText(color, 50, "color");
        CheckText(styleTags, 200, "style_tags");
        CheckText(notes, 500, "notes");
        if (!GarmentCatalog.Categories.ContainsKey(category ?? "")) throw new ArgumentException("Unknown garment category.");
        if (warmth is < 1 or > 5 || formality is < 1 or > 5) throw new ArgumentException("Warmth and formality must be between 1 and 5.");
        Id = id; Name = name; Category = category!; Warmth = warmth; Formality = formality;
        Color = color; StyleTags = styleTags; Notes = notes;
    }

    public static void CheckText(string? value, int max, string field, bool required = false)
    {
        var length = value?.EnumerateRunes().Count() ?? 0;
        if (required && length == 0 || length > max) throw new ArgumentException($"{field} must contain {(required ? 1 : 0)}–{max} characters.");
    }
}
