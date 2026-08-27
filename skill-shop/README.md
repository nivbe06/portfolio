# Skill Shop

A catalogue that turns scattered individual AI hacks into repeatable practice.

> Rebuilt clean as a demonstration of a pattern I ran in production for a
> marketing organisation. No employer data, code, or content. Generic domain,
> synthetic examples.

## The problem

AI adoption inside a company does not fail for lack of enthusiasm. It fails
because thirty people solve the same problem thirty different ways, in private,
with no way to find each other's work and no way to tell a good solution from a
dangerous one. Six months in you have a pile of prompts nobody trusts and no
idea which ones touch customer data.

Central teams answer this by becoming the bottleneck: every automation gets
built by them, reviewed by them, and queued behind everything else. That does
not scale, and it kills the enthusiasm that made adoption possible.

## The pattern

A shop, not a service desk. People browse what already exists, install it in one
step, and contribute their own back through a path that has a quality gate in it.

**Catalogue.** Every skill is a card: what it does, who it is for, what it needs,
and one line to install. Browsing is the point. If finding an existing skill is
harder than rebuilding it, people rebuild it.

**Registry.** The catalogue is generated from a single registry file, so the
shop cannot drift from what actually ships. Adding a skill means a pull request
against the registry, which means adoption is visible in version control rather
than in a survey.

**Contribution path.** A template that makes the good version of a contribution
the easy one: state the job, declare inputs, declare what it touches.

**Graduation gate.** The part that makes this governance rather than a folder of
prompts. Three states:
- *Sandbox* — anyone can build, nothing is promised, no sensitive data.
- *Reviewed* — a maintainer has read it, inputs and data handling are declared.
- *Published* — it appears in the catalogue and other people are expected to
  rely on it.

Promotion is a pull request, so the standard is legible and the same for
everyone. Nobody waits on a central team to build for them; they wait on review,
which is cheaper and reviewable in public.

## What this demonstrates

Guardrails living in the system rather than in people's habits. The gate is not
a policy document that someone might read. It is the mechanism by which a skill
becomes visible to colleagues, so following it is the path of least resistance.

## In this mock

Static catalogue generated from `registry.yml`, six synthetic skills across
three states, a contribution template, and the promotion checklist.
