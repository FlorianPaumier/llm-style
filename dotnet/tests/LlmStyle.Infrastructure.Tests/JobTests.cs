using LlmStyle.Infrastructure.Jobs;
using LlmStyle.Application.Contracts;
namespace LlmStyle.Infrastructure.Tests;
public class JobTests
{
    [Fact]
    public async Task JobsExposeProgressAndFailureWithoutStoppingTheNextJob()
    {
        using var queue=new JobQueue();
        var failed=queue.Enqueue((_,_)=>throw new InvalidOperationException("Bad photo"));
        var good=queue.Enqueue((report,_)=>{report(new(1,1));return Task.FromResult<object>("ready");});
        using var timeout=new CancellationTokenSource(TimeSpan.FromSeconds(3));
        while(queue.Get(good.JobId).Status is "queued" or "running" || queue.Get(failed.JobId).Status is "queued" or "running") await Task.Delay(10,timeout.Token);
        Assert.Equal("failed",queue.Get(failed.JobId).Status); Assert.Equal("Bad photo",queue.Get(failed.JobId).Error);
        Assert.Equal("ready",queue.Get(good.JobId).Result); Assert.Equal(new JobProgress(1,1),queue.Get(good.JobId).Progress);
    }
}
