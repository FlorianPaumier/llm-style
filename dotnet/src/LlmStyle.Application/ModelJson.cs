using System.Text;
using System.Text.Json;
namespace LlmStyle.Application;

public static class ModelJson
{
    public static JsonDocument Extract(string text)
    {
        var start=text.IndexOfAny(['{','[']);
        if(start<0) throw new JsonException("No JSON in model reply.");
        var reader=new Utf8JsonReader(Encoding.UTF8.GetBytes(text[start..]));
        return JsonDocument.ParseValue(ref reader);
    }
}
