using LlmStyle.Domain.Personas;

namespace LlmStyle.Domain.Tests;

public class PersonaNameTests
{
    [Theory]
    [InlineData(null)]
    [InlineData("")]
    public void RejectsMissingName(string? value)
    {
        Assert.Throws<ArgumentException>(() => new PersonaName(value!));
    }

    [Fact]
    public void RejectsMoreThanFiftyUnicodeCharacters()
    {
        Assert.Throws<ArgumentException>(() => new PersonaName(new string('a', 51)));
        Assert.Throws<ArgumentException>(() => new PersonaName(string.Concat(Enumerable.Repeat("😀", 51))));
    }

    [Theory]
    [InlineData("Me")]
    [InlineData(" Partner ")]
    [InlineData(" ")]
    public void PreservesAcceptedInputLikeTheExistingApi(string value)
    {
        Assert.Equal(value, new PersonaName(value).Value);
    }

    [Fact]
    public void AcceptsFiftyUnicodeCharactersWithoutCountingUtf16SurrogatesTwice()
    {
        var value = string.Concat(Enumerable.Repeat("😀", 50));
        Assert.Equal(value, new PersonaName(value).Value);
    }

    [Fact]
    public void NamesWithTheSameValueAreEqual()
    {
        Assert.Equal(new PersonaName("Me"), new PersonaName("Me"));
    }
}
