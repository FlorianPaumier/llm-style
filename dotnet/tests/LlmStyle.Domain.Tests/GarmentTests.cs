using LlmStyle.Domain.Wardrobes;

namespace LlmStyle.Domain.Tests;
public class GarmentTests
{
    [Fact]
    public void CategoryDerivesTheSlotAndRole()
    {
        var dress = new Garment(1, "Summer dress", "dress", 1, 2);
        Assert.Equal("top", dress.Type);
        Assert.Equal("one_piece", dress.Role);
    }

    [Theory]
    [InlineData("unknown", 2, 2)]
    [InlineData("shirt", 0, 2)]
    [InlineData("shirt", 2, 6)]
    public void RejectsInvalidCategoryOrScores(string category, int warmth, int formality)
        => Assert.Throws<ArgumentException>(() => new Garment(1, "Shirt", category, warmth, formality));
}
