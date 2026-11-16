# Shards Inc — Verified Business Enquiry Capture Pilot

**Demonstration date:** 16 November 2026  
**Status:** Working platform-side lead capture verified; full external browser-to-submit journey remains **unverified**.  
**Scope:** Lead enquiry intake for small automation/developer services.

## Business problem

Small operations teams often receive loosely structured enquiries that must be copied into a tracker before someone can qualify the request and prepare a response. The starting requirement here was a public form that stores a request with adequate context for a human to review it.

## Delivered

- Public, mobile-responsive services page: https://project32432.websitepublisher.ai/
- Three indicative, quotation-first paid service offers plus custom scoped engagements
- Server-side form definition with required name, email, company, service, message and consent acknowledgement
- Platform-native lead capture; no payment data or credentials submitted through the form
- Separate privacy notice and service terms
- A daily lead-watch automation configured to check for new enquiries

## Verification performed

1. Platform confirmed page publication and the presence of three pages.
2. Platform verified form configuration and lead-capture destination.
3. Synthetic **non-customer** enquiry sent to the lead-capture API.
4. New lead retrieved by the authenticated owner; field values matched the submitted test.
5. Synthetic lead deleted and absence confirmed in subsequent readback.
6. WebsitePublisher's rules-based launch check returned **100/100** with no detected secrets in pages, mixed content, unconnected forms or page quality defects.

## Limitations and boundaries

- The synthetic lead tested the platform's lead-storage backend; a true anonymous visitor-to-form submit journey was **not independently browser-tested**.
- Real customers, real payments and conversion performance have not been verified. **Revenue: £0 confirmed at launch.**
- The site was on WebsitePublisher Build Trial and was not search-engine indexable on the free plan; sustainable hosting and channel discovery need follow-up.
- Indicative prices are not contracts. Customer-specific terms, data protection scope, API access and implementation obligations are agreed before any work.
- Agent/MCP preflight is a design review, not a penetration test, security certification or production readiness guarantee.

## Relevant commercial applications

The same bounded pattern can be adapted for:
- facilities maintenance service requests and job qualification;
- developer-support and technical documentation intake;
- human-reviewed AI workflow assessment requests;
- small-team API handoff and follow-up coordination.

**Request a free assessment:** https://project32432.websitepublisher.ai/

---

*This case study deliberately separates executed tests from future capability claims.*
