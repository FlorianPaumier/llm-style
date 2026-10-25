using System.Collections.Concurrent;
using System.Threading.Channels;
using LlmStyle.Application;
using LlmStyle.Application.Contracts;
namespace LlmStyle.Infrastructure.Jobs;

public sealed class JobQueue : IJobQueue, IDisposable
{
    private sealed record Work(string Id,Func<Action<JobProgress>,CancellationToken,Task<object>> Run);
    private readonly Channel<Work> channel=Channel.CreateBounded<Work>(128);
    private readonly ConcurrentDictionary<string,(JobStatus Status,DateTimeOffset Created)> jobs=new();
    private readonly CancellationTokenSource stop=new();
    public JobQueue() { for(var i=0;i<2;i++) _=Task.Run(ProcessAsync); }
    public JobCreated Enqueue(Func<Action<JobProgress>,CancellationToken,Task<object>> work)
    {
        foreach(var (key,value) in jobs)
            if(value.Status.Status is "done" or "failed" && value.Created<DateTimeOffset.UtcNow.AddHours(-1)) jobs.TryRemove(key,out _);
        var id=Guid.NewGuid().ToString("N")[..16]; jobs[id]=(new(id,"queued"),DateTimeOffset.UtcNow);
        if(!channel.Writer.TryWrite(new(id,work))) { jobs.TryRemove(id,out _); throw new StyleException(503,"The work queue is full; try again shortly."); }
        return new(id,$"/api/jobs/{id}");
    }
    public JobStatus Get(string id)=>jobs.TryGetValue(id,out var value)?value.Status:throw new StyleException(404,"Job not found (unknown or expired).");
    private void Set(string id,Func<JobStatus,JobStatus> change)=>jobs.AddOrUpdate(id,_=>throw new InvalidOperationException(),(_,value)=>(change(value.Status),value.Created));
    private async Task ProcessAsync()
    {
        try
        {
            await foreach(var work in channel.Reader.ReadAllAsync(stop.Token))
            {
                Set(work.Id,s=>s with { Status="running" });
                try
                {
                    var result=await work.Run(p=>Set(work.Id,s=>s with { Progress=p }),stop.Token);
                    Set(work.Id,s=>s with { Status="done",Result=result });
                }
                catch(Exception e) { Set(work.Id,s=>s with { Status="failed",Error=e.Message }); }
            }
        }
        catch(OperationCanceledException) when(stop.IsCancellationRequested) { }
    }
    public void Dispose() { channel.Writer.TryComplete(); stop.Cancel(); }
}
