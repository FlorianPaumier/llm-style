using System.Globalization;
using System.Text.Json;
using LlmStyle.Application.Contracts;
using LlmStyle.Domain.Outfits;
using LlmStyle.Domain.Wardrobes;
namespace LlmStyle.Application;

public sealed partial class StyleApp
{
    private void ValidateRecommend(RecommendInput input)
    {
        Garment.CheckText(input.Mood,500,"mood",true); Garment.CheckText(input.Activity,200,"activity");
        if(!OutfitPolicy.Formality.ContainsKey(input.Occasion) || input.Count is <1 or >5 || input.WeatherOverrideC is < -60 or >60 || input.WeatherOverrideC is {} t && !double.IsFinite(t)) throw new ArgumentException("Invalid occasion, temperature or option count.");
        if(input.PersonaIds is not null && input.PersonaIds.Any(id=>!store.ListPersonas().Any(p=>p.Id==id))) throw new ArgumentException("Unknown persona ID.");
    }
    public async Task<Recommendation> RecommendAsync(RecommendInput input,CancellationToken cancellationToken=default)
    {
        input=new RecommendInput { Mood=input.Mood,Occasion=input.Occasion,Activity=input.Activity,Count=input.Count,WeatherOverrideC=input.WeatherOverrideC,PersonaIds=input.PersonaIds?.ToList() };
        ValidateRecommend(input); var settings=store.GetSettings(); var people=store.ListPersonas();
        var selected=input.PersonaIds is {Count:>0} ? input.PersonaIds.Distinct().Select(id=>people.Single(p=>p.Id==id)).ToArray() : [people[0]];
        var notes=new List<string>(); Weather today;
        if(input.WeatherOverrideC is {} temp) { today=new(settings.City,temp,temp,0,0,0,DateTimeOffset.UtcNow.ToString("O")); notes.Add("Weather manually overridden."); }
        else
        {
            try { today=await weather.CurrentAsync(settings.City,cancellationToken); }
            catch(Exception e) when(e is not OperationCanceledException || !cancellationToken.IsCancellationRequested)
            {
                today=new(settings.City,15,15,0,0,0,DateTimeOffset.UtcNow.ToString("O")); notes.Add("Live weather unavailable; assumed a mild 15°C. You can set the temperature manually.");
            }
        }
        var outputs=new List<PersonaOutfit>(); var coordination=new List<string>(); var seed=Random.Shared.Next();
        foreach(var person in selected)
        {
            var items=store.Wardrobe(person.Id); var byId=items.ToDictionary(i=>i.Id);
            var candidates=OutfitPolicy.Select(items.Select(i=>i.ToGarment()),today.TemperatureC,input.Occasion,seed,input.Activity);
            var recent=store.History(3,person.Id).Select(h=>h.Items).ToList();
            var avoid=recent.SelectMany(x=>x).Select(i=>i.Id).ToHashSet();
            var summaries=recent.Select(x=>string.Join(", ",x.Select(i=>i.Name).Take(5))).ToList();
            for(var option=1;option<=input.Count;option++)
            {
                cancellationToken.ThrowIfCancellationRequested(); var gaps=candidates.Gaps.ToList();
                IReadOnlyList<Garment> picked=[]; var title="No complete outfit possible"; var rationale="Your wardrobe can't cover today's conditions: "+string.Join(" ",gaps); var source="fallback";
                if(candidates.HasRequired)
                {
                    var messages=new List<ChatMessage> { new("system",Prompts.StylistSystem),new("user",BuildPrompt(candidates,input,person,today,coordination,summaries)) };
                    for(var attempt=0;attempt<2;attempt++)
                    {
                        string reply;
                        try { reply=await llm.CompleteAsync(settings,messages,cancellationToken:cancellationToken); }
                        catch(Exception e) when(e is not OperationCanceledException || !cancellationToken.IsCancellationRequested) { break; }
                        try
                        {
                            using var document=ModelJson.Extract(reply); var root=document.RootElement;
                            var ids=root.GetProperty("item_ids"); var picks=new Dictionary<string,int?>();
                            foreach(var key in new[] {"top","layer","bottom","underlayer","shoes","outerwear"})
                                picks[key]=ids.TryGetProperty(key,out var value) && value.ValueKind!=JsonValueKind.Null ? value.GetInt32() : null;
                            var accessories=ids.TryGetProperty("accessories",out var a) && a.ValueKind!=JsonValueKind.Null ? a.EnumerateArray().Select(x=>x.GetInt32()).ToArray() : [];
                            picked=candidates.Validate(picks,accessories);
                            title=root.GetProperty("title").GetString()!; rationale=root.GetProperty("rationale").GetString()!;
                            if(string.IsNullOrWhiteSpace(title)||string.IsNullOrWhiteSpace(rationale)) throw new ArgumentException("Title and rationale are required.");
                            source="llm"; break;
                        }
                        catch(Exception e) when(e is JsonException or ArgumentException or KeyNotFoundException or InvalidOperationException or FormatException or OverflowException)
                        { messages.Add(new("assistant",reply)); messages.Add(new("user",$"Your reply was invalid: {e.Message}. Answer again with the exact JSON shape, using only candidate IDs.")); }
                    }
                    if(source!="llm")
                    {
                        picked=candidates.Fallback(avoid); title="Safe pick"; rationale=Prompts.Fallback;
                        gaps.Add("Stylist model unavailable or returned an unusable answer; showing a safe deterministic pick.");
                    }
                }
                var outfit=picked.Select(g=>new OutfitItem(g.Type,byId[g.Id])).ToArray();
                var history=store.AddHistory(input,person.Id,today,picked.Select(g=>g.Id).ToArray(),title,rationale,source);
                outputs.Add(new(person.Id,person.Name,title,outfit,rationale,source,gaps,history,option));
                var summary=string.Join(", ",picked.Select(g=>g.Name)); if(option==1 && summary.Length>0) coordination.Add(summary);
                summaries.Add(summary); avoid.UnionWith(picked.Select(g=>g.Id));
            }
        }
        var first=outputs[0]; return new(first.Title,first.Outfit,first.Rationale,first.Source,notes.Concat(outputs.SelectMany(o=>o.Gaps)).Distinct().ToArray(),today,first.HistoryId,outputs);
    }
    private static string BuildPrompt(CandidateSet candidates,RecommendInput input,Persona person,Weather weather,IReadOnlyList<string> coordination,IReadOnlyList<string> recent)
    {
        var weatherSummary=$"{weather.TemperatureC.ToString("0",CultureInfo.InvariantCulture)}°C (feels like {weather.ApparentTemperatureC.ToString("0",CultureInfo.InvariantCulture)}°C); rain {weather.PrecipitationMm} mm; wind {weather.WindSpeedKmh} km/h";
        var rows=string.Join("\n",candidates.All.Select(g=>$"- {g.Type} | id {g.Id} | {g.Category} | {g.Name} | color: {g.Color ?? "n/a"} | tags: {g.StyleTags ?? "n/a"} | warmth {g.Warmth} | formality {g.Formality}"));
        var personaNotes=string.IsNullOrWhiteSpace(person.Description)?"":Prompts.PersonaNotes.Replace("{description}",person.Description);
        if(person.Gender is "male" or "female") personaNotes+=Prompts.GenderNotes.Replace("{phrase}",person.Gender=="male"?"a man":"a woman");
        return Prompts.StylistUser.Replace("{weather_summary}",weatherSummary).Replace("{occasion}",input.Occasion).Replace("{mood}",input.Mood)
            .Replace("{activity_notes}",string.IsNullOrWhiteSpace(input.Activity)?"":Prompts.ActivityNotes.Replace("{activity}",input.Activity))
            .Replace("{persona_notes}",personaNotes).Replace("{coordination}",coordination.Count==0?"":Prompts.Coordination.Replace("{summaries}",string.Join("; ",coordination)))
            .Replace("{recent}",recent.Count==0?"":Prompts.Recent.Replace("{recent_outfits}",string.Join("; ",recent)))
            .Replace("{candidates}",rows).Replace("{variety_rule}",recent.Count==0?Prompts.NoRecent:Prompts.Variety).Replace("{{","{").Replace("}}","}");
    }
}
