using System.Net;
using System.Text;
using LlmStyle.Application;
using LlmStyle.Application.Contracts;
using LlmStyle.Infrastructure.Integrations;
namespace LlmStyle.Infrastructure.Tests;
public class IntegrationClientTests
{
    private sealed class Handler(Func<HttpRequestMessage,Task<HttpResponseMessage>> respond) : HttpMessageHandler
    { protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request,CancellationToken ct)=>respond(request); }
    [Fact]
    public async Task OllamaSendsVisionImagesAndReadsTheChatMessage()
    {
        using var http=new HttpClient(new Handler(async request=>
        {
            Assert.Equal("/api/chat",request.RequestUri!.AbsolutePath);
            var body=await request.Content!.ReadAsStringAsync(TestContext.Current.CancellationToken); Assert.Contains("gemma3:4b",body); Assert.Contains("images",body);
            return new(HttpStatusCode.OK) {Content=new StringContent("{\"message\":{\"content\":\"[]\"}}",Encoding.UTF8,"application/json")};
        }));
        using var client=new OllamaClient(http);
        Assert.Equal("[]",await client.CompleteAsync(new(),[new("user","Clothes",["aW1hZ2U="])],true, TestContext.Current.CancellationToken));
    }
    [Fact]
    public void JsonParserHandlesFencesAndBracesInsideStrings()
    {
        using var parsed=ModelJson.Extract("```json\n{\"title\":\"A } moment\"}\n``` extra");
        Assert.Equal("A } moment",parsed.RootElement.GetProperty("title").GetString());
    }
}
