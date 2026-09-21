# AI_USE.md — HW3

## 1. What I used an AI assistant for, and what I did myself

I had it explain the concepts first --> what actually makes a session cookie "secure", why a signed
client-side cookie isn't automatically invalidated just by clearing server state, and what
"SemanticSplitterNodeParser" is doing differently from a fixed-size splitter -- before
accepting any code.

It helped gather the ~270KB corpus of real FDA/USDA/CDC recall and outbreak documents in
`corpus/` (a mix of individually fetched pages and a bulk snapshot from the public openFDA
API). But every actual
command in this submission -- installing packages, fetching the corpus, running the retrieval
pipeline, starting the server, logging in and out, and every `curl` test -- was run by me, on
my own MacBook Air, one command at a time. Every screenshot in `screenshots/` is a real
screenshot I took of my own browser session, and every line in `RUN_LOG.txt` is real console
output from my own terminal, not generated or simulated.

## 2. One AI-produced output that was wrong/unsuitable

While re-running the "prove a logged-out session can't be reused" test, the very first result
I got looked wrong: the first `curl` check (hitting `/dashboard` immediately after logging in,
before doing anything else) returned `HTTP 302` (redirected away) instead of the `HTTP 200` I
expected for a session that had just been created seconds ago.

## 3. How I detected the problem

The result didn't match what should happen for a freshly-created session. Looking at the
timestamps in my own terminal output, I noticed about 6-7 minutes had actually passed between
when I logged in and when I ran the test -- and the app's default idle timeout is 5 minutes. So the "wrong" result wasn't a bug
at all: my session had genuinely gone idle and expired in the background, and the app
correctly rejected it.

## 4. What I changed, and why it works now

I didn't need to change any code --> the app was behaving correctly the whole time. To get a
clean before/after comparison for this report (login works -> logout -> old cookie rejected,
all within a couple of seconds so idle timeout doesn't also kick in and muddy the result), I
just re-ran the same login/logout/reuse sequence back-to-back as one paste instead of typing
each command separately with delays in between. That gave the expected `200 -> 302 -> 302`
sequence, which is now what's recorded in `RUN_LOG.txt`. I also think the accidental first
result is worth keeping a note about, since it's a genuine, unplanned demonstration that idle
timeout works, on top of the deliberate `IDLE_TIMEOUT_SECONDS=3` test I ran separately for that
specific requirement.
