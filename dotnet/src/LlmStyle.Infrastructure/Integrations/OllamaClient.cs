using System.Net.Http.Json;
using System.Text.Json;
using System.Text.Json.Serialization;
using LlmStyle.Application;
using LlmStyle.Application.Contracts;
namespace LlmStyle.Infrastructure.Integrations;

public sealed class OllamaClient(HttpClient? http=null) : ILlmClient, IDisposable
{
    private readonly HttpClient client=http ?? new() {Timeout=TimeSpan.FromSeconds(300)};
    private static readonly JsonSerializerOptions Options=new() {PropertyNamingPolicy=JsonNamingPolicy.SnakeCaseLower,DefaultIgnoreCondition=JsonIgnoreCondition.WhenWritingNull};
    public async Task<string> CompleteAsync(StyleSettings settings,IReadOnlyList<ChatMessage> messages,bool vision=false,CancellationToken cancellationToken=default)
    {
        if(!Uri.TryCreate(settings.OllamaUrl,UriKind.Absolute,out var uri) || uri.Scheme is not ("http" or "https")) throw new StyleException(503,"Invalid Ollama URL.");
        try
        {
            using var response=await client.PostAsJsonAsync(settings.OllamaUrl.TrimEnd('/')+"/api/chat",new {model=vision?settings.VisionModel:settings.Model,messages,stream=false,format="json",options=new {temperature=vision?0.2:0.7}},Options,cancellationToken);
            response.EnsureSuccessStatusCode(); using var document=await JsonDocument.ParseAsync(await response.Content.ReadAsStreamAsync(cancellationToken),cancellationToken:cancellationToken);
            return document.RootElement.GetProperty("message").GetProperty("content").GetString() ?? throw new JsonException("Empty model reply.");
        }
        catch(Exception e) when(e is HttpRequestException or JsonException or KeyNotFoundException || e is OperationCanceledException && !cancellationToken.IsCancellationRequested)
        { throw new StyleException(503,"Ollama is unavailable or the selected model isn't ready. Check Settings and your local Ollama server."); }
    }
    public void Dispose()=>client.Dispose();
}
