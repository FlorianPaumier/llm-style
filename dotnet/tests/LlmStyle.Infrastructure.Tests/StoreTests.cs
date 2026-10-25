using LlmStyle.Application.Contracts;
using LlmStyle.Infrastructure.Storage;

namespace LlmStyle.Infrastructure.Tests;
public sealed class StoreTests : IDisposable
{
    private readonly string directory = Path.Combine(Path.GetTempPath(), "llm-style-tests", Guid.NewGuid().ToString("N"));
    private SqliteStyleStore Open() => new(Path.Combine(directory, "llm_style.db"), new StyleSettings());

    [Fact]
    public void PersonasPersistAndCannotDeleteTheLastPerson()
    {
        var store = Open();
        Assert.Single(store.ListPersonas());
        Assert.Equal(400, Assert.Throws<StyleException>(() => store.DeletePersona(1)).StatusCode);
        var partner = store.SavePersona(new() { Name = "Partner", Description = "No hats" });
        Assert.Equal("No hats", Open().ListPersonas().Single(p => p.Id == partner.Id).Description);
    }

    [Fact]
    public void ItemEditsRetainPhotosAndFilteringIsPerPerson()
    {
        var store=Open(); var partner=store.SavePersona(new() { Name="Partner" });
        var item=store.SaveItem(new() { Name="Linen shirt", Category="shirt", Warmth=2, Formality=2 });
        store.SetPhoto(item.Id,"1.jpg");
        var input=item.ToInput(); input.Name="New name"; input.PersonaId=partner.Id;
        var edited=store.SaveItem(input,item.Id);
        Assert.True(edited.HasPhoto);
        Assert.Empty(store.ListItems(new()).Items);
        Assert.Single(store.ListItems(new(PersonaId:partner.Id,Q:"New",Sort:"name")).Items);
        Assert.Equal(409,Assert.Throws<StyleException>(()=>store.DeletePersona(partner.Id)).StatusCode);
        store.DeleteItem(item.Id); store.DeletePersona(partner.Id);
    }
    [Fact]
    public void PartialSettingsAndPersonUpdatesDistinguishMissingFromNull()
    {
        var store=Open(); store.UpdateSettings(new Dictionary<string,string?> { ["city"]="Toronto", ["model"]="custom" });
        var updated=store.UpdateSettings(new Dictionary<string,string?> { ["city"]=null });
        Assert.Equal("Paris",updated.City); Assert.Equal("custom",updated.Model);
        var person=store.SavePersona(new() { Name="Partner",Description="No hats",Gender="female" });
        var kept=store.SavePersona(new() { Name="New" },person.Id,new HashSet<string> { "name" });
        Assert.Equal("No hats",kept.Description); Assert.Equal("female",kept.Gender);
        var cleared=store.SavePersona(new(),person.Id,new HashSet<string> { "description","gender" });
        Assert.Null(cleared.Description); Assert.Equal("unspecified",cleared.Gender);
    }
    [Fact]
    public async Task WornCountingIsAtomicAndIdempotentUnderConcurrentRequests()
    {
        var store=Open(); var item=store.SaveItem(new() { Name="Shirt",Category="shirt",Warmth=2,Formality=2 });
        var history=store.AddHistory(new() { Mood="Happy" },1,new("Paris",18,18,0,0,0,"now"),[item.Id],"Look","Reason","fallback");
        var results=await Task.WhenAll(Enumerable.Range(0,8).Select(_=>Task.Run(()=>store.MarkWorn(history))));
        Assert.Single(results,r=>!r.AlreadyWorn); Assert.Equal(1,store.GetItem(item.Id).TimesWorn);
        Assert.NotNull(store.GetHistory(history).WornAt);
    }

    [Fact]
    public async Task ConcurrentPartialPersonaUpdatesKeepBothChanges()
    {
        var store=Open();
        for(var iteration=0;iteration<40;iteration++)
        {
            store.SavePersona(new() {Name="Original",Gender="unspecified"},1);
            using var ready=new Barrier(2);
            await Task.WhenAll(
                Task.Run(()=>{ready.SignalAndWait();store.SavePersona(new() {Name="Changed"},1,new HashSet<string>{"name"});}),
                Task.Run(()=>{ready.SignalAndWait();store.SavePersona(new() {Gender="female"},1,new HashSet<string>{"gender"});}));
            var person=store.ListPersonas()[0]; Assert.Equal("Changed",person.Name); Assert.Equal("female",person.Gender);
        }
    }

    [Fact]
    public async Task ConcurrentPartialSettingsUpdatesKeepBothChanges()
    {
        var store=Open();
        for(var iteration=0;iteration<30;iteration++)
        {
            store.UpdateSettings(new Dictionary<string,string?> { ["city"]="Paris",["model"]="original" });
            using var ready=new Barrier(2);
            await Task.WhenAll(
                Task.Run(()=>{ready.SignalAndWait();store.UpdateSettings(new Dictionary<string,string?> { ["city"]="Toronto" });}),
                Task.Run(()=>{ready.SignalAndWait();store.UpdateSettings(new Dictionary<string,string?> { ["model"]="changed" });}));
            var settings=store.GetSettings(); Assert.Equal("Toronto",settings.City); Assert.Equal("changed",settings.Model);
        }
    }
    public void Dispose() { Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools(); if (Directory.Exists(directory)) Directory.Delete(directory, true); }
}
