# Brain Onboarding

The path that takes a non-technical person from zero to a working context layer.

> Rebuilt clean as a demonstration of a pattern I ran in production. No employer
> data, code, or content. Generic domain, synthetic examples.

## The problem

Agents and humans give different answers to the same question when they are
reading different things. Most organisations respond by writing documentation
that goes stale within a quarter, because nothing in the daily loop forces it to
be updated and nobody reads it anyway.

A context layer only works if two things are true: it is readable by a language
model without preprocessing, and updating it is a side effect of work people
already do. Miss either one and it decays into another wiki.

## The pattern

**Guided setup, not a blank repository.** A new person answers a short sequence
of questions and ends with a populated structure, not an empty folder. First
useful interaction inside ten minutes, because that is the window in which
people decide whether a system is real.

**Structure that a model can read.** Every file carries typed frontmatter, so
retrieval narrows by metadata before anything is read. Grep before read. This
matters more than any prompt: the fastest way to make a model unreliable is to
hand it everything.

**A stated update process.** The layer names who updates what and on which
trigger. Updates ride on work that already happens — a decision gets logged when
it is made, a status changes when it changes — rather than depending on a
scheduled review nobody runs.

**One worked example, end to end.** Setup, first question, first update, and
what the model sees at each step. Abstract descriptions of context layers
convince nobody; a trace of one working does.

## What this demonstrates

Shared truth as an operating system rather than a document. The design question
is not what to write down; it is what makes writing it down the cheapest option
at the moment the information exists.

## In this mock

A guided setup flow, a populated example layer with typed frontmatter, the
update rules, and a walkthrough of one full loop from question to updated state.
