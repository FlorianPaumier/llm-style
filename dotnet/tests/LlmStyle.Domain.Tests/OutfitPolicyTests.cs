using LlmStyle.Domain.Outfits;
using LlmStyle.Domain.Wardrobes;
namespace LlmStyle.Domain.Tests;
public class OutfitPolicyTests
{
    private static Garment G(int id,string category,int warmth=2)=>new(id,category,category,warmth,2);
    [Theory]
    [InlineData(30,1,1)] [InlineData(18,1,2)] [InlineData(12,2,3)] [InlineData(5,3,4)] [InlineData(-10,4,5)]
    public void TemperatureSelectsWarmthBand(double temp,int low,int high)=>Assert.Equal((low,high),OutfitPolicy.WarmthBand(temp));
    [Fact]
    public void ALayerCannotReplaceThePrimaryTop()
    {
        var set=OutfitPolicy.Select([G(1,"cardigan"),G(2,"jeans"),G(3,"sneakers")],18,"casual",1);
        Assert.False(set.HasRequired); Assert.Contains(set.Gaps,g=>g.Contains("primary top"));
    }
    [Fact]
    public void DressReplacesBottomAndRejectsAnExtraPairOfJeans()
    {
        var set=OutfitPolicy.Select([G(1,"dress"),G(2,"jeans"),G(3,"sneakers")],18,"casual",1);
        Assert.True(set.HasRequired);
        Assert.Throws<ArgumentException>(()=>set.Validate(new Dictionary<string,int?> { ["top"]=1,["bottom"]=2,["shoes"]=3 },[]));
        Assert.Equal(2,set.Validate(new Dictionary<string,int?> { ["top"]=1,["shoes"]=3 },[]).Count);
    }
    [Fact]
    public void UnderlayersDoNotGoUnderJeansAndUnknownIdsAreRejected()
    {
        var set=OutfitPolicy.Select([G(1,"shirt"),G(2,"jeans"),G(3,"sneakers"),G(4,"tights")],18,"casual",1);
        Assert.Throws<ArgumentException>(()=>set.Validate(new Dictionary<string,int?> { ["top"]=1,["bottom"]=2,["underlayer"]=4,["shoes"]=3 },[]));
        Assert.Throws<ArgumentException>(()=>set.Validate(new Dictionary<string,int?> { ["top"]=999,["bottom"]=2,["shoes"]=3 },[]));
    }
    [Fact]
    public void FallbackAvoidsRecentItemsAndSkipsHotWeatherScarves()
    {
        var set=OutfitPolicy.Select([G(1,"shirt",1),G(2,"t_shirt",1),G(3,"shorts",1),G(4,"sandals",1),G(5,"scarf",5)],30,"casual",1);
        var chosen=set.Fallback(new HashSet<int> { 1 });
        Assert.Contains(chosen,g=>g.Id==2); Assert.DoesNotContain(chosen,g=>g.Id==1 || g.Id==5);
    }
}
