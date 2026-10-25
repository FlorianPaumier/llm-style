using System.Text;

namespace LlmStyle.Domain.Personas;

public sealed record PersonaName
{
    public string Value { get; }

    public PersonaName(string value)
    {
        // Python validates Unicode characters, not UTF-16 code units; preserve that contract.
        if (value is null || value.EnumerateRunes().Count() is < 1 or > 50)
            throw new ArgumentException("A persona name must contain 1–50 characters.", nameof(value));

        Value = value;
    }
}
