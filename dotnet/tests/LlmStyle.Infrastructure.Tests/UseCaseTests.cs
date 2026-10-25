using LlmStyle.Application;
using LlmStyle.Application.Contracts;
using LlmStyle.Infrastructure.Storage;
using LlmStyle.Infrastructure.Photos;
using LlmStyle.Infrastructure.Jobs;
namespace LlmStyle.Infrastructure.Tests;
public sealed class UseCaseTests : IDisposable
{
    private readonly string directory=Path.Combine(Path.GetTempPath(),"llm-style-tests",Guid.NewGuid().ToString("N"));
    private readonly JobQueue jobs=new();
    private sealed class FakeWeather : IWeatherClient
    { public int Calls; public Task<Weather> CurrentAsync(string city,CancellationToken ct=default) { Calls++; throw new StyleException(503,"Weather offline"); } }
    private sealed class FakeLlm(params string[] replies) : ILlmClient
    {
        private int index;
        public Task<string> CompleteAsync(StyleSettings s,IReadOnlyList<ChatMessage> m,bool vision=false,CancellationToken ct=default)
            => index<replies.Length ? Task.FromResult(replies[index++]) : throw new StyleException(503,"Ollama offline");
    }
    private StyleApp App(params string[] replies)=>new(new SqliteStyleStore(Path.Combine(directory,"db.sqlite"),new()),new LocalPhotoStorage(Path.Combine(directory,"images")),new FakeWeather(),new FakeLlm(replies),jobs);
    [Fact]
    public async Task OfflineRecommendationUsesRealWardrobePersistsHistoryAndMarksOnlyOneOptionWorn()
    {
        var app=App();
        foreach(var category in new[] {"shirt","t_shirt","jeans","chinos","sneakers"}) app.SaveItem(new() {Name=category,Category=category,Warmth=2,Formality=2});
        var result=await app.RecommendAsync(new() { Mood="Calm",Count=2 }, TestContext.Current.CancellationToken);
        Assert.Equal(2,result.Outfits.Count); Assert.Equal("fallback",result.Source);
        Assert.Equal(15,result.Weather.TemperatureC); Assert.All(result.Outfits,o=>Assert.Equal(3,o.Outfit.Count));
        Assert.NotEqual(result.Outfits[0].Outfit[0].Item.Id,result.Outfits[1].Outfit[0].Item.Id);
        app.MarkWorn(result.Outfits[1].HistoryId!.Value);
        Assert.Null(app.GetHistory(result.Outfits[0].HistoryId!.Value).WornAt);
        Assert.NotNull(app.GetHistory(result.Outfits[1].HistoryId!.Value).WornAt);
    }
    [Fact]
    public async Task InvalidModelIdsRetryThenUseOnlyActualWardrobeItems()
    {
        var app=App("{\"title\":\"Bad\",\"item_ids\":{\"top\":999},\"rationale\":\"x\"}","garbage");
        foreach(var category in new[] {"shirt","jeans","sneakers"}) app.SaveItem(new() {Name=category,Category=category,Warmth=2,Formality=2});
        var result=await app.RecommendAsync(new() {Mood="Happy",WeatherOverrideC=18}, TestContext.Current.CancellationToken);
        Assert.Equal("fallback",result.Source); Assert.DoesNotContain(result.Outfit,p=>p.Item.Id==999);
    }
    [Fact]
    public async Task PhotoClassificationKeepsValidNeighboursAndQuickAddGivesEachItemItsOwnPhoto()
    {
        const string reply="[{\"name\":\"Shirt\",\"category\":\"shirt\",\"warmth\":2,\"formality\":2},{\"name\":\"Bad\",\"category\":\"not-clothes\"},{\"name\":\"Jeans\",\"category\":\"jeans\",\"warmth\":2,\"formality\":2}]";
        var app=App(reply); var items=await app.QuickAddAsync(new("outfit.jpg",[1,2,3]),1, TestContext.Current.CancellationToken);
        Assert.Equal(2,items.Count); Assert.All(items,i=>Assert.True(i.HasPhoto));
        app.DeleteItem(items[0].Id); Assert.Equal(new byte[]{1,2,3},app.ItemPhoto(items[1].Id).Bytes);
    }
    [Fact]
    public async Task EmptyWardrobeReturnsNamedGapsInsteadOfInventedClothes()
    {
        var result=await App().RecommendAsync(new() { Mood="Quiet",WeatherOverrideC=20 }, TestContext.Current.CancellationToken);
        Assert.Empty(result.Outfit); Assert.NotEmpty(result.Gaps); Assert.NotNull(result.HistoryId);
    }
    [Fact]
    public void PhotoReplacementDoesNotRequireTheModelOrChangeItemDetails()
    {
        var app=App(); var item=app.SaveItem(new() {Name="Shirt",Category="shirt",Warmth=2,Formality=2});
        app.UploadPhoto(item.Id,new("one.jpg",[1,2])); app.UploadPhoto(item.Id,new("two.png",[3,4]));
        Assert.Equal(new byte[]{3,4},app.ItemPhoto(item.Id).Bytes); Assert.Equal("Shirt",app.GetItem(item.Id).Name);
    }

    [Fact]
    public async Task ValidModelChoiceIsUsedAndBracesInRationaleRemainIntact()
    {
        var app=App("{\"title\":\"A good day\",\"item_ids\":{\"top\":1,\"bottom\":2,\"shoes\":3},\"rationale\":\"Use {soft} pieces.\"}");
        foreach(var category in new[]{"shirt","jeans","sneakers"}) app.SaveItem(new() {Name=category,Category=category,Warmth=2,Formality=2});
        var result=await app.RecommendAsync(new() {Mood="Quiet",WeatherOverrideC=18},TestContext.Current.CancellationToken);
        Assert.Equal("llm",result.Source); Assert.Equal("A good day",result.Title); Assert.Equal("Use {soft} pieces.",result.Rationale);
        Assert.Equal(3,result.Outfit.Count);
    }
    [Fact]
    public async Task CoordinatedPeopleGetIndependentOptionsHistoriesAndOneWeatherFetch()
    {
        var climate=new FakeWeather();
        var app=new StyleApp(new SqliteStyleStore(Path.Combine(directory,"db.sqlite"),new()),new LocalPhotoStorage(Path.Combine(directory,"images")),climate,new FakeLlm(),jobs);
        var partner=app.SavePersona(new() {Name="Partner"});
        foreach(var id in new[]{1,partner.Id})
        foreach(var category in new[]{"shirt","jeans","sneakers"}) app.SaveItem(new() {Name=category,Category=category,Warmth=2,Formality=2,PersonaId=id});
        var result=await app.RecommendAsync(new() {Mood="Together",PersonaIds=[1,partner.Id],Count=2},TestContext.Current.CancellationToken);
        Assert.Equal(4,result.Outfits.Count); Assert.Equal(1,climate.Calls);
        Assert.All(result.Outfits,o=>Assert.All(o.Outfit,p=>Assert.Equal(o.PersonaId,p.Item.PersonaId)));
        Assert.Equal(2,app.History(personaId:1).Count); Assert.Equal(2,app.History(personaId:partner.Id).Count);
    }
    public void Dispose() { jobs.Dispose(); Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools(); if(Directory.Exists(directory)) Directory.Delete(directory,true); }
}
