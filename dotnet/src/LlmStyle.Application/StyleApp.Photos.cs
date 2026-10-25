using System.Text.Json;
using LlmStyle.Application.Contracts;
using LlmStyle.Domain.Wardrobes;
namespace LlmStyle.Application;

public sealed partial class StyleApp
{
    public async Task<IReadOnlyList<DraftItem>> ClassifyAsync(PhotoUpload upload,CancellationToken cancellationToken=default)
    {
        ValidateUpload(upload); var settings=store.GetSettings();
        var grouped=string.Join("\n",GarmentCatalog.Categories.GroupBy(p=>p.Value.Slot).Select(g=>$"{g.Key}: {string.Join(", ",g.Select(p=>p.Key))}"));
        var messages=new List<ChatMessage> {new("system",Prompts.VisionSystem),new("user",Prompts.VisionUser.Replace("{categories}",grouped).Replace("{{","{").Replace("}}","}"),[Convert.ToBase64String(upload.Bytes)])};
        for(var attempt=0;attempt<2;attempt++)
        {
            string reply;
            try { reply=await llm.CompleteAsync(settings,messages,vision:true,cancellationToken:cancellationToken); }
            catch(Exception e) when(e is not OperationCanceledException || !cancellationToken.IsCancellationRequested) { throw new StyleException(503,$"Photo classification failed: {e.Message}"); }
            try
            {
                using var document=ModelJson.Extract(reply); var root=document.RootElement;
                var elements=root.ValueKind==JsonValueKind.Array ? root.EnumerateArray().ToArray() : [root]; var valid=new List<ItemInput>();
                foreach(var raw in elements)
                {
                    try
                    {
                        string? Text(string key)=>raw.TryGetProperty(key,out var value) && value.ValueKind!=JsonValueKind.Null ? value.GetString() : null;
                        var input=new ItemInput { Name=Text("name")?.Trim() ?? "",Category=Text("category") ?? "",Type=Text("type"),Color=Text("color")?.Trim(),
                            Warmth=checked((int)raw.GetProperty("warmth").GetDouble()),Formality=checked((int)raw.GetProperty("formality").GetDouble()),StyleTags=Text("style_tags")?.Trim() };
                        if(string.IsNullOrWhiteSpace(input.Name)) throw new ArgumentException("Empty name.");
                        _=input.ToGarment(); valid.Add(input);
                    }
                    catch(Exception e) when(e is JsonException or ArgumentException or InvalidOperationException or KeyNotFoundException or OverflowException or FormatException) { }
                }
                if(valid.Count==0) throw new ArgumentException("Model found no valid wearable items.");
                return valid.Take(8).Select(i=>new DraftItem(i.Name,i.Category,i.ToGarment().Type,i.Color,i.Warmth,i.Formality,i.StyleTags,photos.SaveDraft(upload))).ToArray();
            }
            catch(Exception e) when(e is JsonException or ArgumentException)
            { messages.Add(new("assistant",reply)); messages.Add(new("user",$"Your reply was invalid: {e.Message}. Answer again with a JSON array of valid clothing items.")); }
        }
        throw new StyleException(503,"The photo model returned no usable clothing drafts after one retry.");
    }
    public async Task<IReadOnlyList<ItemView>> QuickAddAsync(PhotoUpload upload,int? personaId,CancellationToken cancellationToken=default)
    {
        var target=personaId ?? ListPersonas()[0].Id;
        if(!ListPersonas().Any(p=>p.Id==target)) throw new ArgumentException("Unknown persona ID.");
        var drafts=await ClassifyAsync(upload,cancellationToken); var saved=new List<ItemView>();
        foreach(var draft in drafts) { cancellationToken.ThrowIfCancellationRequested(); saved.Add(SaveItem(draft.ToInput(target))); }
        return saved;
    }
}
