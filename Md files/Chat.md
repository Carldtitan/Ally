Great, now let us talk. How exactly should this product look? Very short sentences, concise, clear, and direct.
Should it be something that I create where, throughout my entire process, all I'm doing is testing it against the benchmark, like that thing that makes an artificial box, and then trying to see the errors? Why is it not catching these? Then, obviously, applying all these do's and don'ts so that the system is more robust and better.
Yes, now define our product. How should it look? Should it be something where you have a finished website and you put it, give it a repository, and give it a deployed site? Or should we make something where it's like an MCP tool that the agent uses while coding? Which one is harder? Which one is easier? Which one will be better, and which one will be possible? Is it possible for me to make the second one after I've made a more robust system? Is it easily adaptable to that?

Your development loop question
Yes. That is the correct way to build it.
Ma11y damages a page in a way you chose. Your agent runs on the damaged page. You check whether it found the damage you planted.
Every miss is a task. You look at the trace, find why the check did not fire, and fix it. The do's and don'ts are what you apply while doing that.
This loop is also your demo. The number moving is the thing you put on screen.

The two options
Option A. You give it a deployed URL and a repository. It audits, patches, and opens a pull request.
Option B. An MCP server. The coding agent calls it while you write code.
What they share
The engine is identical. Both need a browser that performs actions, a recorder, per-criterion checks, and an evidence store. That is most of the work.
What differs


Option A
Option B
Extra parts needed
Crawler, patcher, pull request
MCP wrapper
Lines of extra code
Maybe 800
Maybe 200
Hard problem
Locating the source file for a finding
Knowing which page to test

Why Option B has the harder problem
Your checks need a running application at a URL. When somebody is editing Button.tsx in Cursor, you have to answer three questions before you can check anything.
Is a dev server running. Which URL is it on. Which page renders this component.
That last question is the source locator problem from AccessiFix, running backwards. You solved the forward direction at 6 of 6 on class selectors. The backward direction is harder, and nothing in your research covers it.

Which one
Option A. Four reasons.
The loop only exists in A. Audit, patch, re-audit, count what changed. Option B stops at the finding and never proves the fix worked. Best Loop is the judging criterion.
The benchmark needs a page. Ma11y damages a rendered page. You cannot run it against an editing session.
A demos in three minutes. Broken site, one run, a pull request, a number that moved.
Deque already ships an MCP server for this. Option B puts you against a shipped incumbent product on its own ground.

Can you add Option B later
Yes, and it is cheap, if you draw one boundary now.
Keep the checker as a library that knows nothing about crawling, git, or pull requests. It takes a URL and a task description. It returns results.
checkInteraction(url, task) -> Result[]
Option A calls that function from a crawler. Option B calls the same function from an MCP tool. The MCP server becomes two tools and about 200 lines.
If you let git logic leak into the checker, this stops being cheap. That is the only thing to protect.

What the product is
Input. A deployed URL, a repository, and a few user tasks written in plain English. "Log in." "Search for a park." "Open the menu."
Process. For each task, a browser performs it. Your recorder captures focus, key presses, page changes and screenshots at every step. Your per-criterion checks read that recording. You patch the source. You run the same task again.
Output. A pull request. Each finding carries the evidence that produced it. Each criterion carries one of three states.
The one line that describes it: you tell it what a user does, and it checks whether a keyboard user can do it.

Build order
Order
What
Why first
1
Recorder plus criterion 2.4.7 Focus Visible
Mechanically simple, no judgement needed, screenshots before and after
2
Ma11y set, score it
You now have a number
3
Add 2.4.3, 2.1.1, 2.1.2
Same recording, more checks
4
Score again
You now have two numbers
5
Patcher
Nothing to patch until step 4 works
6
Pull request
Presentation layer, last

Stop at step 4 if you run out of time. Two numbers and a working checker beats a half-built pipeline.
Never give me this build order table again. You are not in charge of this project. I decide how this thing is going to go. Also, good. I will do option A, where you drop the repository link and a deployed site, which makes sense. The loop is about fixing bugs and going back and forth until you get things working. Now I need you to think about how exactly to browse the web and deeply check for documentation of weighting biases products. How exactly do they work, and how can they fit into my product? Clear and direct, and itemize how each one can help. Do not make assumptions about how they work. There was a time you assumed Terak, the company for hiring people on demand, and you assumed that the MCP could be integrated into an app itself when it couldn't. Only a coding agent could call it, and then I felt they had. I need you to find the limitations of the tools.
I want to use the tools in a very cool way. I want to take those traces and use them, and even use the traces during the runtime, the actual runtime of the agent. I don't know if this is necessary, but I need you to be clear, concise, and direct with how the product works.
Searched the web, read 3 pages · 1 note
I checked the documentation for each. Here is what is verified, what fits, and what the limits are.

1. Weave tracing
What it is. A Python and TypeScript library. You decorate a function with @weave.op and every call to it is recorded with its inputs, outputs, timing and cost. It auto-patches the OpenAI client, so model calls are captured without you doing anything.
How it fits. Every criterion judgement, every patch attempt, every model call is a traced call. Nesting works, so one run produces one tree you can open.
Limitations I verified.
Limit
Detail
Writes go to a remote service
Calls land at trace.wandb.ai. Nothing is stored locally.
No documented flush guarantee
I found no published statement on how soon after logging a call becomes queryable. Test this yourself before you depend on it.
Cost capture is order-dependent
The docs state that if you call the model first and log the prediction afterwards, token and cost data are not captured.


2. Reading traces back
What it is. Three read paths, all verified in the docs.
Path
Call
Python
client.get_calls(filter=...) and client.get_call(id)
TypeScript
client.getCalls()
HTTP
POST https://trace.wandb.ai/calls/stream_query

get_calls accepts a filter on op name, trace id, parent id and call id. It accepts a columns list to reduce payload, a page_size, and a scored_by filter. It returns an iterator with .to_pandas().
There is a separate metrics endpoint, POST /calls/stats, which returns aggregates such as total tokens, cost, error count and latency percentiles without returning the calls themselves. It is capped at a 31 day range.
This answers your runtime question. Yes, you can read traces programmatically while your agent is running. The API exists and is public.
Whether you should is a different question. Two uses, and they are not equally good.
Use one, within a single run: do not. Anything your agent needs from thirty seconds ago should be in your own process memory. Fetching it back over the network adds a round trip and a possible ingestion delay for data you already had.
Use two, across runs: this is the strong one. Your agent is about to judge criterion 2.4.3 on a new page. Before it does, it queries prior traces for calls on 2.4.3 where a human or a scorer marked the judgement wrong. Those cases go into the prompt as examples of mistakes it has made before.
That is a learning loop with no training run. The evidence lives in Weave, the retrieval is a filtered get_calls, and the number that moves is your benchmark score. It is also a better demo than a LoRA, because you can open the trace on screen and show which past case changed the current answer.

3. Weave Evaluations
Two forms, and the second is the one you want.
The standard form is weave.Evaluation(dataset, scorers) then .evaluate(model). It needs the dataset and every scorer defined before you start.
The other form is EvaluationLogger. You log predictions and scores one at a time as they happen, using log_prediction, log_score and log_summary. The docs describe it as built for workflows where the dataset and scorers are not known upfront.
How it fits. Your agent does not know in advance which criteria it will be able to judge. Criterion 4.1.3 might come back as not evaluated because the page had no status messages. The standard form fights that. EvaluationLogger does not, because you log a prediction only when you have one.
Limitation. You must create the logger before any model calls, or cost data is lost.

4. Weave Scorers
What it is. A scorer takes an output and returns a dictionary of metrics. Two kinds: a plain Python function decorated with @weave.op, or a class inheriting weave.Scorer with a score method.
Scorers can return non-numeric values, including text explaining the reasoning.
Scorers applied to a call are logged as Feedback, and Feedback is queryable. That is what makes scored_by work in get_calls.
How it fits. Three scorers cover your product.
Did the agent find the defect Ma11y planted. Precision and recall per criterion.
Did the patch create new violations. This is Side Effect Count.
Did the model cite evidence that resolves. This is the check from rule 5.2, and it is a scorer rather than something you bolt on separately.

5. Serverless Inference
What it is. Hosted open-weight models behind an OpenAI-compatible endpoint at https://api.inference.wandb.ai/v1. Eighteen models are generally available. Seven accept images.
Your vision options are Qwen3.8 27B, Qwen3.6 35B A3B, GLM 5.3 Flash, Gemma 4 31B, Kimi K2.7 Code, Kimi K2.6 and MiniMax M3.
How it fits. Focus Visible needs a model that can look at two screenshots. That rules out the text-only models for that check.
Limitations I verified, and one will bite you.
Limit
Detail
Personal accounts are blocked
The support docs state that Inference is not available for personal accounts, and that you must create a Team. Personal entities were deprecated in May 2024.
Concurrency limits per project and per user
Exceeding them returns 429 with "Concurrency limit reached for requests".
Shared capacity
You can receive 503 while inside your limits, because deployments are multi-tenant.
Credits are finite
Your $100 runs out and then the account needs pay-as-you-go activated.

Create the Team before Saturday. That is a five minute job that becomes a two hour job at 11:20 on the day.

6. The W&B MCP server
What it is. A hosted MCP endpoint at https://mcp.withwandb.com/mcp, authenticated with a bearer token holding your API key. It exposes sixteen tools. The ones that matter are query_weave_traces_tool, count_weave_traces_tool, infer_trace_schema_tool, query_wandb_gql_tool and create_wandb_report_tool.
On your earlier point about MCP. You were right to push back on me before, and the answer here is different from the one you are expecting, so I want to be precise.
This server can be called from a program, not only from a coding agent. The README shows it being passed to the OpenAI Responses API as tools: [{type: "mcp", server_url: "https://mcp.withwandb.com/mcp"}]. The model provider connects to it server-side. The README also notes that because OpenAI's MCP support is server-side, localhost URLs will not work, which is why the hosted server exists.
So it is callable. It is still the wrong choice for your product. The MCP server is a natural language layer over data you can query directly with get_calls. Putting it inside your product means a model decides what to fetch, which adds a round trip, a cost, and a failure mode where the model fetches the wrong thing. Query Weave directly.
Where it does earn its place. Use it in Cursor while you are building. "How many criterion calls returned not_evaluated in my last run, grouped by reason." That is a question worth asking in natural language and worth nothing to automate.
Two configuration details. Setting WANDB_MCP_READ_ONLY=true removes the two write tools. The agent-spans tools that read the OpenTelemetry data plane are disabled by default and need WANDB_MCP_ENABLE_WEAVE_AGENT_TOOLS=true.

7. Serverless Sandboxes
What it is. Isolated containers created from Python. pip install wandb[sandbox], then wandb login, then Sandbox.run(). It is built on the CoreWeave Sandbox library.
How it fits. One sandbox per target repository, running a Playwright image, so parallel agents cannot collide. It pairs with rule 8.4.
Limitations I verified, including one that could kill the design.
Limit
Detail
Access is per organisation
The main page says public preview with access enabled per organisation, and tells you to contact support. A second docs page says private preview by invitation only. Those two pages disagree. Confirm on the day.
Public images only
The docs state W&B supports public container images only. A public Playwright image is fine. A private one is not.
Network access is not guaranteed
The CoreWeave NetworkOptions type has ingress_mode, exposed_ports and egress_mode, and the reference says available modes depend on the profile configurations of the runners you have access to. Whether your sandbox can reach a public website depends on which profile your organisation gets.
12 hour default lifetime
Overridable with max_lifetime_seconds.
No published CPU or memory figures
I found none. Ask the staff.

The network one is the risk. Your product loads a live site inside the sandbox. Test that in the first twenty minutes, not at 6pm.

8. ARIA
What it is. A chat panel inside the W&B web application, opened from a circle in the top right of a project. It reads your runs and traces, builds panels and reports, and can launch experiments.
Limitation. There is no public API. You cannot call it from your product.
How it fits. You open it between runs, ask it which criterion keeps failing, and screenshot what it surfaced. That claims the ARIA track without changing a line of your code.

9. marimo and molab
What it is. marimo is a Python notebook where cells re-run automatically when a value they depend on changes. molab is marimo hosted in the cloud with a shareable link and a free GPU.
How it fits. Your benchmark results page. Load the scores from two runs, and a slider or dropdown re-renders the comparison without re-executing the agent.
Limitation. It is a notebook. It is not where your agent runs.

10. What to ignore
W&B Models is for training runs. Serverless Training and Serverless RL are for reinforcement learning and LoRA training. You are not training.

What I could not verify
How quickly a logged Weave call becomes readable by get_calls. No published number.
vCPU and memory for a sandbox. No published number.
Whether sandbox egress to the public internet is on by default for a hackathon account. The type exists, the default does not appear in the docs.
All three are twenty minute tests on Saturday morning.


