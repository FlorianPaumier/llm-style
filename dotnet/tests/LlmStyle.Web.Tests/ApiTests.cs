using System.Net;
using System.Net.Http.Json;
using System.Text;
using System.Text.Json;
using LlmStyle.Application;
using LlmStyle.Application.Contracts;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.DependencyInjection.Extensions;

namespace LlmStyle.Web.Tests;
public class ApiTests : IDisposable
{
    private readonly string data=Path.Combine(Path.GetTempPath(),"llm-style-api",Guid.NewGuid().ToString("N"));
    private WebApplicationFactory<Program>? host;
    private HttpClient Client(string environment="Development")
    {
        host=new WebApplicationFactory<Program>().WithWebHostBuilder(b=>b.UseEnvironment(environment).ConfigureAppConfiguration((_,c)=>c.AddInMemoryCollection(new Dictionary<string,string?> { ["LLM_STYLE_DATA_DIR"]=data })));
        host=host.WithWebHostBuilder(b=>b.ConfigureServices(s=>{s.RemoveAll<ILlmClient>();s.AddSingleton<ILlmClient,OfflineLlm>();}));
        return host.CreateClient(new WebApplicationFactoryClientOptions {BaseAddress=new Uri("https://localhost")});
    }
    private sealed class OfflineLlm : ILlmClient
    { public Task<string> CompleteAsync(StyleSettings settings,IReadOnlyList<ChatMessage> messages,bool vision=false,CancellationToken ct=default)=>throw new StyleException(503,"Model offline"); }
    [Fact]
    public async Task DownloadInfoAndQrAreAvailable()
    {
        using var client=Client();
        var response=await client.GetAsync("/api/app/download", TestContext.Current.CancellationToken); Assert.Equal(HttpStatusCode.OK,response.StatusCode);
        Assert.Contains("primary_url",await response.Content.ReadAsStringAsync(TestContext.Current.CancellationToken));
        var qr=await client.GetStringAsync("/api/app/qr.svg", TestContext.Current.CancellationToken); Assert.Contains("<svg",qr);
    }
    [Fact]
    public async Task AsyncRecommendationsReturnPollableResultsAndWornIsIdempotent()
    {
        using var client=Client();
        foreach(var category in new[]{"shirt","jeans","sneakers"}) await client.PostAsJsonAsync("/api/items",new{name=category,category,warmth=2,formality=2}, TestContext.Current.CancellationToken);
        var response=await client.PostAsJsonAsync("/api/outfits/recommend/async",new{mood="Calm",weather_override_c=18,count=1}, TestContext.Current.CancellationToken);
        Assert.Equal(HttpStatusCode.Accepted,response.StatusCode);
        using var body=JsonDocument.Parse(await response.Content.ReadAsStringAsync(TestContext.Current.CancellationToken)); var statusUrl=body.RootElement.GetProperty("status_url").GetString();
        using var timeout=new CancellationTokenSource(TimeSpan.FromSeconds(3)); JsonElement result;
        while(true)
        {
            using var job=JsonDocument.Parse(await client.GetStringAsync(statusUrl,timeout.Token));
            var state=job.RootElement.GetProperty("status").GetString();
            Assert.NotEqual("failed",state);
            if(state=="done") {result=job.RootElement.GetProperty("result").Clone();break;}
            await Task.Delay(10,timeout.Token);
        }
        Assert.Equal("fallback",result.GetProperty("source").GetString()); Assert.Equal(3,result.GetProperty("outfit").GetArrayLength());
        var id=result.GetProperty("history_id").GetInt32();
        await client.PostAsync($"/api/history/{id}/worn",null, TestContext.Current.CancellationToken);
        var repeated=await client.PostAsync($"/api/history/{id}/worn",null, TestContext.Current.CancellationToken);
        Assert.Contains("\"already_worn\":true",await repeated.Content.ReadAsStringAsync(TestContext.Current.CancellationToken));
    }
    [Fact]
    public async Task ItemCrudUsesTheExistingSnakeCaseContractAndIsIsolated()
    {
        using var client=Client();
        var response=await client.PostAsJsonAsync("/api/items",new {name="Navy shirt",category="shirt",warmth=2,formality=2}, TestContext.Current.CancellationToken);
        Assert.Equal(HttpStatusCode.Created,response.StatusCode);
        var item=JsonDocument.Parse(await response.Content.ReadAsStringAsync(TestContext.Current.CancellationToken)).RootElement;
        Assert.Equal("top",item.GetProperty("type").GetString()); Assert.True(item.TryGetProperty("persona_id",out _));
        var id=item.GetProperty("id").GetInt32();
        var page=await client.GetStringAsync("/api/items?q=Navy&page_size=1", TestContext.Current.CancellationToken); Assert.Contains("\"total\":1",page);
        Assert.Equal(HttpStatusCode.NoContent,(await client.DeleteAsync($"/api/items/{id}", TestContext.Current.CancellationToken)).StatusCode);
        Assert.Equal(HttpStatusCode.NotFound,(await client.GetAsync($"/api/items/{id}", TestContext.Current.CancellationToken)).StatusCode);
        Assert.True(File.Exists(Path.Combine(data,"llm_style.db")));
    }
    [Theory]
    [InlineData("{\"name\":\"Bad\",\"category\":\"shirt\",\"warmth\":9,\"formality\":2}")]
    [InlineData("{\"name\":\"Bad\",\"warmth\":2,\"formality\":2}")]
    [InlineData("{\"name\":\"Bad\",\"category\":\"shirt\",\"type\":\"bottom\",\"warmth\":2,\"formality\":2}")]
    [InlineData("{\"name\":\"Bad\",\"category\":\"shirt\",\"warmth\":2,\"formality\":2,\"unknown\":true}")]
    public async Task InvalidItemPayloadsAreRejectedWithoutSaving(string json)
    {
        using var client=Client(); var response=await client.PostAsync("/api/items",new StringContent(json,Encoding.UTF8,"application/json"), TestContext.Current.CancellationToken);
        Assert.Equal((HttpStatusCode)422,response.StatusCode); Assert.Contains("detail",await response.Content.ReadAsStringAsync(TestContext.Current.CancellationToken));
    }
    [Fact]
    public async Task SettingsPatchPreservesAbsentAndResetsNull()
    {
        using var client=Client();
        await client.PutAsJsonAsync("/api/settings",new {city="Toronto",model="my-model"}, TestContext.Current.CancellationToken);
        var response=await client.PutAsync("/api/settings",new StringContent("{\"city\":null}",Encoding.UTF8,"application/json"));
        var json=await response.Content.ReadAsStringAsync(TestContext.Current.CancellationToken); Assert.Contains("Paris",json); Assert.Contains("my-model",json);
    }

    [Fact]
    public async Task ProductionPreservesJsonErrorsAndStatusCodes()
    {
        using var client=Client("Production");
        var missing=await client.GetAsync("/api/items/999",TestContext.Current.CancellationToken);
        Assert.Equal(HttpStatusCode.NotFound,missing.StatusCode); Assert.Contains("detail",await missing.Content.ReadAsStringAsync(TestContext.Current.CancellationToken));
        var invalid=await client.PostAsJsonAsync("/api/items",new {name="Invalid"},TestContext.Current.CancellationToken);
        Assert.Equal((HttpStatusCode)422,invalid.StatusCode); Assert.Equal("application/json",invalid.Content.Headers.ContentType!.MediaType);
    }
    [Theory]
    [InlineData("/api/classify/async","photo","failed")]
    [InlineData("/api/classify/bulk","photos","done")]
    public async Task SinglePhotoFailuresFailTheJobButBulkPreservesPerPhotoErrors(string path,string field,string expected)
    {
        using var client=Client(); using var multipart=new MultipartFormDataContent();
        multipart.Add(new ByteArrayContent([1,2,3]),field,"photo.jpg");
        var response=await client.PostAsync(path,multipart,TestContext.Current.CancellationToken);
        Assert.Equal(HttpStatusCode.Accepted,response.StatusCode);
        using var created=JsonDocument.Parse(await response.Content.ReadAsStringAsync(TestContext.Current.CancellationToken));
        var url=created.RootElement.GetProperty("status_url").GetString(); using var timeout=new CancellationTokenSource(TimeSpan.FromSeconds(3));
        while(true)
        {
            using var status=JsonDocument.Parse(await client.GetStringAsync(url,timeout.Token));
            var state=status.RootElement.GetProperty("status").GetString();
            if(state is "done" or "failed") { Assert.Equal(expected,state); break; }
            await Task.Delay(10,timeout.Token);
        }
    }
    public void Dispose() { host?.Dispose(); Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools(); if(Directory.Exists(data)) Directory.Delete(data,true); }
}
