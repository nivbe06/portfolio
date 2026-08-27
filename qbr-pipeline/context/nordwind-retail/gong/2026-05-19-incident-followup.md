---
source: gong
source_id: gong-2026-05-19-001
date: 2026-05-19
tenant_id: nordwind-retail
title: Follow-up on the mobile app error rate
participants: ["Henrik Sole (Nordwind, Head of Digital)", "account team"]
entities: [Mobile App, api_error_rate, integration_health]
visibility: customer_safe
---

Called after Nordwind's mobile app saw elevated 5xx responses during the week of
11 May.

Henrik confirmed the cause was on their side: a release on 11 May shipped a
client that retried failed requests immediately and without a backoff, which
turned a small number of genuine errors into a sustained spike.

> "It was our release. The retry loop had no backoff, so one failure became
> forty. We shipped the fix on the Thursday."
> - Henrik Sole, 03:58

Fix deployed 14 May. Henrik asked to see the error rate by week at the QBR so he
can show his own leadership that it is closed.
