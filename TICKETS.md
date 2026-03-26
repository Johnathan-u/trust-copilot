# Trust Copilot — Product Tickets

## A. UI/UX Polish

### A-1: Increase text contrast on dark panels
Audit all secondary and muted text colors across the application, particularly in table rows, card descriptions, and sidebar labels. Update CSS variables and Tailwind classes to meet WCAG AA contrast ratios (minimum 4.5:1 for normal text, 3:1 for large text). Test against the dark background panels used throughout the dashboard, documents list, and questionnaire views. Pay special attention to timestamps, status labels, and helper text that currently blend into the background.

### A-2: Add light mode / theme toggle
Implement a theme toggle in the sidebar footer or user settings that switches between the current dark theme and a new light theme. Use Tailwind's `dark:` class strategy with a `class`-based toggle on the root element, persisted to localStorage. Create a light color palette that maintains the brand identity while improving readability for extended document review sessions. Ensure all components, charts, and the public Trust Center page respect the selected theme.

### A-3: Hide or label incomplete modules
The Admin page is currently empty and the Requests module shows a perpetual "Loading requests..." state with no content. Either remove these items from the sidebar navigation entirely or add a visible "Coming Soon" badge next to them. This prevents new users from clicking into broken or empty pages and thinking the product is unfinished. Revisit and unhide each module only when its core functionality is complete and tested.

### A-4: Add in-app onboarding checklist
After a user's first login, display a persistent onboarding checklist widget (e.g., bottom-right corner or a dedicated onboarding page) that walks them through: upload your first evidence document, upload a questionnaire, generate AI answers, review answers, and export. Each step should link directly to the relevant page and auto-complete when the user performs the action. Dismiss the checklist once all steps are done, with an option to re-access it from settings.

### A-5: Improve public Trust Center page layout
The public-facing Trust Center currently lists articles in a basic layout with minimal branding. Add support for the workspace's logo, brand colors, and a custom header/banner. Improve the article card design with better typography, icons per category, and a more professional layout. Add a footer with company info and a more prominent "Request trust information" CTA button.

### A-6: Show coverage progress inside each questionnaire
When a user opens a specific questionnaire, display a mini coverage dashboard at the top showing: percentage of questions answered, average confidence level across answers, number of blind spots, and evidence strength for that questionnaire. This contextualizes the compliance analytics within the user's immediate workflow rather than requiring them to navigate to a separate Coverage page. Use compact bar/ring charts consistent with the main Coverage module styling.

### A-7: Fix Review module flow
The audit found that the Review module directs users back to the questionnaire page to initiate answer generation, but the actual answer-editing interface was unreachable. Trace the full user journey from questionnaire upload through answer generation to review and ensure every link and button works end-to-end. If answer generation is an async background job, show clear status indicators (processing, ready for review, reviewed). The review interface should allow inline editing, approval, flagging, and commenting on individual answers.

---

## B. Trust Center Enhancements

### B-1: NDA gating for Trust Center documents
Allow workspace admins to mark certain Trust Center articles or documents as NDA-protected. When a visitor tries to access gated content, prompt them to fill out a form (name, email, company) and accept the NDA terms before granting access. Store the acceptance record for audit purposes and send the admin a notification when someone signs. This mirrors competitor functionality and is expected by enterprise buyers evaluating vendor security posture.

### B-2: Content expiration on Trust Center articles
Add an optional expiry date field to Trust Center articles. When an article's expiry date passes, automatically hide it from the public Trust Center page and notify the workspace admin that the content needs to be refreshed. This prevents stale compliance documentation (e.g., last year's SOC 2 report) from remaining publicly visible. Display a "Last updated" and "Valid until" date on each article for visitor transparency.

### B-3: Auto-populate Trust Center from approved answers
When questionnaire answers are reviewed and marked as approved, offer a one-click action to publish relevant answers as Trust Center articles grouped by framework or subject category. The system should de-duplicate and merge answers about the same topic across multiple questionnaires into a single coherent article. This reduces manual effort in maintaining the Trust Center and ensures the public-facing content stays aligned with actual questionnaire responses.

### B-4: Trust Center viewer analytics
Track and display analytics on Trust Center usage: which articles are viewed, by whom (if they provided their info via NDA gating or request forms), how often, and when. Present this data in an admin-facing analytics dashboard within the Trust Center management section. This gives compliance teams visibility into what prospects and customers care about and helps prioritize which documentation to maintain. Include basic metrics like total views, unique visitors, and most-viewed articles.

### B-5: Customer-specific Trust Center pages
Allow admins to generate unique Trust Center URLs tailored to specific customers or vendors, each containing a curated subset of articles and documents relevant to that relationship. Track access per customer-specific page separately. This enables targeted compliance disclosure rather than a one-size-fits-all public page, which is particularly valuable when different customers have different compliance requirements or NDA terms.

---

## C. Vendor Risk / Requests Module

### C-1: Complete the Requests module CRUD
Implement full create, read, update, and delete functionality for vendor requests. An admin should be able to create a new request specifying the vendor's name, contact email, questionnaire template, and due date. The system should send the vendor an email with a secure link to fill out the questionnaire. Track request status (sent, viewed, in progress, completed, overdue) and display it in a table with filtering and sorting.

### C-2: Vendor risk scoring
After a vendor submits their questionnaire responses, automatically calculate a risk score based on answer completeness, identified gaps, and framework coverage. Display the score as a simple rating (e.g., Low/Medium/High or a numeric score out of 100) on the vendor's request record. Allow admins to override or annotate the score with manual notes. This transforms the Requests module from a simple inbox into a vendor risk management tool.

### C-3: Vendor questionnaire intake via secure link
Build a public-facing form that vendors can access via a unique secure link (no Trust Copilot login required). The form should present the questionnaire questions, allow file uploads for evidence, and support save-and-resume functionality. When the vendor submits, their responses flow back into the workspace's Requests module for review. Include branding from the requesting company and clear instructions for the vendor.

### C-4: Vendor status tracking dashboard
Create a dashboard view within the Requests module that shows all active vendor assessments at a glance: how many are pending, in progress, completed, or overdue. Include visual indicators (color-coded status pills, progress bars) and the ability to send reminder emails to vendors who haven't responded by the due date. Allow filtering by vendor name, status, framework, and date range.

---

## D. Knowledge Base & Data Moat

### D-1: Cross-questionnaire answer library
When a user approves an answer during the review process, save it to a workspace-level answer library indexed by framework, subject category, and question keywords. This library persists across questionnaires so the workspace accumulates institutional knowledge over time. Display the library as a searchable, filterable table in a new "Answer Library" section. Allow manual editing and versioning of stored answers.

### D-2: Answer reuse suggestions
During answer generation for a new questionnaire, before calling the LLM, check the workspace's answer library for previously approved answers to similar questions. If matches are found (based on semantic similarity and framework/subject overlap), present them as suggested answers that the user can accept, edit, or override with a fresh AI-generated response. This reduces API costs, improves consistency across questionnaires, and speeds up the review process.

### D-3: Confidence scores on every answer
Display a visible confidence indicator (high, medium, low — or a percentage) on each AI-generated answer based on the strength and relevance of the retrieved evidence passages. Show the specific evidence passages that back each answer, with links to the source document and page/section. Highlight answers with low confidence in a distinct color so reviewers can prioritize their attention on the responses most likely to need manual intervention.

### D-4: Evidence link citations in exports
When exporting completed questionnaires to XLSX or DOCX, include a "Source" column (XLSX) or footnote (DOCX) for each answer citing the specific uploaded document and relevant passage it was derived from. This gives the questionnaire recipient confidence that answers are evidence-backed, not generic AI text. Format the citations cleanly so they look professional in the exported artifact and match the formatting conventions of the target questionnaire.

---

## E. Integrations

### E-1: AWS integration
Build an integration that connects to a customer's AWS account via IAM role assumption or access keys and pulls security-relevant configurations as evidence: IAM policies, CloudTrail status, S3 bucket policies, encryption settings, VPC configurations, and Security Hub findings. Store the pulled data as evidence documents that can be used in questionnaire answer generation. Include a setup wizard that guides users through creating the necessary IAM role with read-only permissions.

### E-2: GCP integration
Connect to Google Cloud Platform to pull IAM policies, audit logs, organization policies, encryption configurations, and Security Command Center findings. Present these as structured evidence documents within the Documents module. This enables continuous evidence collection from GCP environments rather than requiring users to manually export and upload screenshots or PDFs of their cloud configurations.

### E-3: Azure integration
Connect to Microsoft Azure to pull Azure Active Directory configurations, role assignments, Microsoft Defender for Cloud findings, and resource security policies. Map pulled data to relevant compliance framework controls (e.g., SOC 2 CC6.1 maps to access control configurations). This rounds out the three major cloud providers and is essential for enterprise customers running multi-cloud environments.

### E-4: Okta / Google Workspace integration
Pull user access reviews, MFA enrollment status, SSO configurations, and authentication policies from Okta or Google Workspace. These are among the most frequently asked-about controls in security questionnaires (access management, identity verification, authentication strength). Having this data automatically ingested and kept current eliminates one of the most tedious evidence-gathering tasks for compliance teams.

### E-5: GitHub / GitLab integration
Pull branch protection rules, required code review policies, CI/CD pipeline configurations, dependency scanning results, and secret scanning alerts from GitHub or GitLab. Map these to relevant questionnaire topics like secure development lifecycle, change management, and vulnerability management. This is particularly valuable for SOC 2 and ISO 27001 questionnaires that frequently ask about software development practices.

### E-6: Jira integration
Connect to Jira to pull security-related tickets, vulnerability remediation tracking, incident response records, and risk register items. This provides evidence for questionnaire topics around vulnerability management, incident response, and risk assessment processes. Allow users to tag specific Jira projects or labels as compliance-relevant so only pertinent tickets are ingested.

### E-7: Expand Slack / Teams evidence ingestion
The existing Slack evidence ingestion should be expanded to include Microsoft Teams. Add the ability to auto-tag ingested messages by framework and subject category using the existing framework classifier. Allow users to configure which channels are monitored and set up keyword-based triggers so only compliance-relevant conversations are captured as evidence.

---

## F. Landing Page & Marketing Site

### F-1: Rewrite landing page hero copy
Replace the current hero section with pain-point-first messaging: "A 200-question security questionnaire takes 8-12 hours. Trust Copilot completes it in minutes — with citations from your actual compliance docs." Follow with a clear CTA button ("Send us your questionnaire" or "Start free"). The copy should immediately communicate the outcome, not the technology. Test multiple headlines and measure click-through rates.

### F-2: Add pricing prominently to the landing page
Either embed pricing cards directly on the landing page or add a highly visible "Pricing" link in the top navigation. Feature three tiers: Sandbox (limited, low-cost entry point), Deal-Saver at $399/month with 15 credits (primary offering), and Enterprise (custom). The $399 price point should feel justified by the value context: "Companies spend $50K-$150K/year on questionnaires. Trust Copilot: $4,788/year." Make the pricing impossible to miss.

### F-3: Add a "How it works" section
Create a visual 3-step section on the landing page: (1) Upload your compliance docs, (2) Upload the questionnaire, (3) Get evidence-backed answers in minutes. Use icons or illustrations for each step and keep the copy focused on speed and accuracy. Optionally add a fourth step: "Export and send — deal unblocked." This reduces perceived complexity for visitors who don't yet understand the product.

### F-4: Add social proof section
Create a section on the landing page for customer testimonials, company logos, and usage statistics. Initially populate with metrics like "X questionnaires completed" or "Y questions answered" pulled from actual platform data. As customers come in, replace with real testimonials and logos (with permission). Even early-stage social proof like "Built for SOC 2, HIPAA, ISO 27001 certified companies" signals credibility.

### F-5: Add ROI calculator
Build an interactive calculator on the landing page or a dedicated `/roi` page. Inputs: number of questionnaires per year, average questions per questionnaire, average hourly cost of the person who handles them. Outputs: hours saved per year, dollar value saved, comparison to Trust Copilot subscription cost. Pre-fill with industry averages (50 questionnaires/year, 200 questions each, $75/hour) so visitors see an immediate result.

### F-6: Create a product demo video
Record a 60-90 second screencast showing the full workflow: uploading a document, uploading a questionnaire, AI generating answers with citations, reviewing, and exporting. Keep it fast-paced with callouts highlighting key moments (framework auto-detection, evidence citations, coverage analytics). Embed on the landing page above the fold or immediately below the hero section. Host on YouTube for SEO value.

### F-7: SEO blog content
Write and publish blog posts targeting high-intent search queries: "how to answer a SOC 2 questionnaire," "security questionnaire automation tools," "SIG questionnaire template and tips," "CAIQ questionnaire guide." Each post should provide genuine value while naturally positioning Trust Copilot as the solution. Aim for 1,500-2,500 words per post with proper heading structure, internal links, and a CTA at the end.

---

## G. Distribution & Go-to-Market

### G-1: Build a target prospect list
Identify 100 companies that meet the ideal customer profile: 20-500 employees, SOC 2 or ISO 27001 certified, in SaaS/fintech/healthtech/cloud infrastructure. Use LinkedIn Sales Navigator, Crunchbase, or similar tools to find compliance managers, GRC analysts, VP of Security, or CTOs at these companies. Organize the list in a spreadsheet with company name, contact name, title, email, LinkedIn URL, and relevant compliance certifications.

### G-2: Launch cold outreach campaign
Draft a 3-email outbound sequence targeting the prospect list. Email 1: lead with the pain point ("How many hours did your team spend on security questionnaires last quarter?"), introduce Trust Copilot, offer to complete one questionnaire free. Email 2: share a specific ROI stat. Email 3: final follow-up with a case study or demo link. Use a tool like Instantly, Apollo, or Mailshake to automate sending and track opens/replies.

### G-3: Partner with SOC 2 audit firms
Reach out to 10-15 SOC 2 audit firms (Schellman, A-LIGN, Prescient Assurance, Johanson Group, etc.) and propose a referral partnership. Their clients are already dealing with compliance questionnaires and would be warm leads. Offer a revenue share or free credits for referred customers. Frame it as a value-add their firm can offer clients: "We help your clients respond to security questionnaires faster after they get certified."

### G-4: VC portfolio program outreach
Pitch to venture capital firms as a portfolio-wide benefit. Message: "Your portfolio companies all deal with security questionnaires when selling to enterprises. We can handle all of them for a portfolio-wide rate." Target firms with B2B SaaS portfolios (a16z, Sequoia, Bessemer, Costanoa). Even getting into one firm's portfolio program could yield 10-20 customers at once.

### G-5: Product Hunt launch
Prepare a Product Hunt launch with proper assets: logo, tagline ("AI answers security questionnaires in minutes using your actual compliance docs"), description, screenshots, and a maker comment explaining the story. Schedule the launch for a Tuesday or Wednesday. Engage the PH community in advance by commenting on related products. Have a special offer ready for PH visitors (extended trial or first questionnaire free).

### G-6: Create a downloadable whitepaper
Write "The True Cost of Security Questionnaires" — a 5-10 page PDF covering: industry data on questionnaire volume and time costs, the impact on deal velocity, current approaches and their limitations, and how AI automation changes the equation. Gate it behind an email form on the website. Use it as a lead magnet in outbound emails and LinkedIn posts. Include citations from the audit's market data.

---

## H. Proof & Credibility

### H-1: Track and publish accuracy metrics
Instrument the review workflow to measure what percentage of AI-generated answers are approved by reviewers without edits. Track this metric per workspace, per framework, and overall across the platform. Once accuracy consistently exceeds 90%, publish it prominently on the marketing site and in sales materials. This is the single most important proof point for the product's core value proposition.

### H-2: Track and publish time-saved metrics
Measure the elapsed time from questionnaire upload to completed export for each questionnaire processed. Compare against the industry benchmark of 8-12 hours for manual completion. Display aggregate stats in the product dashboard ("You've saved X hours this month") and publish platform-wide averages on the marketing site. Frame it as: "Average completion time: 15 minutes vs. 8 hours manual."

### H-3: Acquire 3 beta customers and collect testimonials
Offer 3 companies free or heavily discounted access in exchange for a written testimonial and permission to use their company name and logo on the website. Target companies at different stages: one startup, one mid-size, one enterprise-adjacent. Guide them through completing at least one real questionnaire and document their experience. A single credible testimonial from a recognizable company is worth more than any feature.

### H-4: Write a case study
After the first real customer completes a questionnaire using Trust Copilot, document the experience in a structured case study: company background, the problem (how many questionnaires they handle, how long it takes), the solution (how they used Trust Copilot), and the results (time saved, accuracy, deal impact). Publish on the website and use in sales outreach. Include specific numbers wherever possible.

### H-5: Publish Trust Copilot's own compliance posture
Use your own Trust Center to publish your security practices: data encryption at rest and in transit, infrastructure security (DigitalOcean, Docker, Caddy TLS), access controls, data handling and retention policies, and incident response procedures. This dogfoods the product and demonstrates credibility. Enterprise buyers will check whether a compliance tool practices what it preaches.

---

## I. Pricing & Monetization

### I-1: Create a free/sandbox tier
Offer a permanently free or very low-cost tier ($25/month) with strict limits: 1 questionnaire per month, 3 document uploads, no exports or watermarked exports, no API access. Position this as "explore the product" not "use it for real work." The goal is to get skeptical buyers into the product so they experience the AI quality firsthand, then convert them to the Deal-Saver tier when they need real output.

### I-2: Add an enterprise tier
Create an Enterprise tier with custom pricing for organizations that need SSO/SAML integration, dedicated support, custom SLAs, higher credit limits, API access, and advanced admin controls. Don't list a price — use a "Contact Sales" CTA. This signals to enterprise buyers that you can meet their procurement requirements and are prepared for their scale.

### I-3: Explore per-framework pricing option
Some customers may only handle SOC 2 questionnaires or only HIPAA. Consider offering framework-specific plans at a lower price point than the full Deal-Saver tier. This could lower the barrier for niche buyers while still maintaining the value-based pricing model. Evaluate whether this segments the market effectively or just cannibalizes the main offering before implementing.

---

## J. Security & Compliance Credentials

### J-1: Pursue SOC 2 Type II certification
Begin the SOC 2 Type II audit process by defining the trust service criteria scope, documenting controls, and selecting an auditor. Use Trust Copilot's own compliance analytics to identify gaps in your own security posture — this is a powerful dogfooding opportunity. SOC 2 certification is table stakes for selling to enterprise compliance teams; without it, many prospects will disqualify you during their own vendor assessment process.

### J-2: Add GDPR compliance documentation
Publish a Data Processing Agreement (DPA) template, document data residency (where customer data is stored geographically), detail data retention and deletion policies, and explain the legal basis for processing. Make these documents downloadable from the Trust Center and the marketing site footer. European customers and any company with European end-users will require this documentation before purchasing.

### J-3: Publish a dedicated security page
Create a `/security` page on the marketing site detailing: encryption standards (AES-256 at rest, TLS 1.3 in transit), infrastructure security (containerized deployment, network isolation, automated backups), access controls (RBAC, MFA, session management), vulnerability management practices, and incident response procedures. This page should be linked from the footer and referenced in sales conversations. It serves as a quick-reference for prospects doing vendor due diligence.

---

## K. Funding & Scaling

### K-1: Prepare a pitch deck
Build a 12-15 slide pitch deck covering: problem (cost and pain of security questionnaires), solution (Trust Copilot), product demo screenshots, market size ($10B+ security automation, $35B+ compliance software), competitive landscape (positioned against Vanta/Drata at 1/10th the price), business model ($399/month credit-based), traction (metrics once available), team, and ask. Keep it visual and narrative-driven, not text-heavy.

### K-2: Identify target investors
Research and list 20-30 seed-stage venture capital firms that invest in security, compliance, or B2B SaaS. Priority targets: Costanoa Ventures (security focus), Unusual Ventures (technical founders), Decibel Partners (enterprise software), Boldstart Ventures (enterprise AI), and YC/Techstars if applying to accelerators. For each firm, identify the partner most likely to be interested and find warm introduction paths via LinkedIn.

### K-3: Explore strategic partnerships
Approach larger GRC and compliance platforms (OneTrust, ServiceNow, Archer) about integration partnerships — Trust Copilot as a questionnaire-response add-on within their ecosystem. Alternatively, explore whether any of these companies would be interested in acquiring the technology to fill a gap in their own product suite. Also consider partnerships with MSPs and MSSPs who serve mid-market compliance needs.

### K-4: Define first hiring plan
When ready to scale beyond solo founder, the first two hires should be: (1) a full-stack engineer to build integrations and expand the platform, and (2) a growth/marketing person to run outbound campaigns, content marketing, and partnerships. Define job descriptions, compensation ranges, and where to source candidates (e.g., YC's Work at a Startup, LinkedIn, AngelList). Prioritize people with compliance industry experience.

---

## L. Pricing Model Overhaul

### L-1: Implement $399/month Deal-Saver tier
Replace the current $25/month subscription with the Deal-Saver plan at $399/month including 15 questionnaire credits. Update the Stripe product and price objects accordingly. Each credit corresponds to approximately 100 questions answered, so a typical 200-question questionnaire consumes 2 credits. This pricing aligns cost with value delivered and requires far fewer customers to reach meaningful revenue.

### L-2: Build credit-based usage system
Add a credit ledger to the backend that tracks per-workspace credit balance, consumption, and purchase history. When a questionnaire is processed, calculate credits consumed based on question count (question_count / 100, rounded up) and deduct from the workspace balance. Store a transaction record linking each deduction to the specific questionnaire. Expose the balance via API so the frontend can display it in real time.

### L-3: Add credit top-up purchasing
Allow workspace admins to purchase additional credit packs on-demand when they exceed their monthly allocation. Create a Stripe one-time payment flow for credit packs (e.g., 5 credits for $149, 10 credits for $279). Upon successful payment, automatically add the credits to the workspace balance. Send an email receipt and update the credit purchase history page.

### L-4: Create one-time "Done-For-You" service tier
Offer a single-questionnaire completion for a flat fee ($199-$499 depending on question count) with no subscription commitment. This serves as the lowest-friction entry point for prospects who aren't ready to commit to a monthly plan. After payment via Stripe Checkout, the questionnaire enters a processing queue and the completed artifact is delivered via email and available for download in the app.

### L-5: Build sandbox tier with deliberate limits
Create a low-cost or free tier that lets users explore the product but caps functionality: limited document uploads, limited questionnaires per month, no export or watermarked exports, basic coverage analytics only. Position this clearly as a testing ground ("Try the AI on your own documents") rather than the real product. The goal is taste, not satisfaction — serious buyers should feel the pull toward Deal-Saver.

### L-6: Redesign the pricing page
Rebuild `/pricing` with three tiers displayed as cards: Sandbox (explore), Deal-Saver at $399/month with 15 credits (recommended, highlighted), and Enterprise (contact sales). Each card should list specific inclusions and limits. Add an FAQ section addressing common objections: "What counts as a credit?", "What happens if I run out?", "Can I cancel anytime?" Include the ROI comparison stat below the cards.

### L-7: Update Stripe products and prices
Create new Stripe Product and Price objects for: Deal-Saver monthly ($399/month recurring), Deal-Saver annual ($3,999/year recurring), credit top-up packs (one-time), and Done-For-You service (one-time). Deprecate the old $25/month and $250/year prices. Update the `STRIPE_PRICE_ID` and `STRIPE_ANNUAL_PRICE_ID` environment variables and the billing routes to reference the new price IDs.

---

## M. Positioning & Messaging Overhaul

### M-1: Reframe landing page around the "deal-stall" moment
Rewrite the landing page hero to focus on the critical moment: "A security questionnaire just landed. Your deal is stalling. We complete it in hours, not days — with evidence from your actual compliance docs." Every element on the page should reinforce this narrative: urgency, speed, accuracy, and deal impact. Remove any generic "AI-powered platform" language and replace with outcome-specific copy.

### M-2: Position as outcome, not tool
Audit all marketing copy, in-app text, and documentation. Replace feature-focused language ("AI-powered questionnaire automation platform") with outcome-focused language ("Complete security questionnaires in minutes, not days. Every answer backed by your real evidence."). The product should feel like hiring an expert, not subscribing to software. This positioning shift should be consistent across the landing page, pricing page, onboarding flow, and email communications.

### M-3: Replace CTA with "Send us your questionnaire"
Change the primary call-to-action across the entire marketing site from "Sign up" or "Start free trial" to "Send us your questionnaire." This aligns with the Done-For-You entry point and immediately communicates that the product delivers results, not access to a dashboard. Secondary CTAs can still offer "Explore the platform" for self-serve users, but the primary action should promise an outcome.

### M-4: Redesign "How it works" around the deal moment
Replace any generic product walkthrough with a narrative flow: Step 1: "Your deal stalls on a security questionnaire." Step 2: "Upload it to Trust Copilot (or send it to us)." Step 3: "Get it back completed with evidence citations — in hours, not days." Step 4: "Send it back and close the deal." Use visuals that show the before (stressed team, stalled deal) and after (completed questionnaire, deal closed).

### M-5: Rewrite all copy to sell outcomes
Go through every page in the application and marketing site. Replace "Upload documents" with "Build your evidence library." Replace "Generate answers" with "Get questionnaires completed." Replace "Compliance coverage analytics" with "See exactly where your gaps are." Every label, heading, and description should answer the user's implicit question: "What does this do for me?" not "What does this feature do?"

---

## N. Done-For-You Service Flow

### N-1: Build public questionnaire intake form
Create a public-facing page (e.g., `/submit`) where prospects can submit a questionnaire without creating an account. The form should collect: company name, contact name, email, questionnaire file upload, optional evidence document uploads, and any special instructions. Upon submission, send a confirmation email and create an internal ticket. This is the top-of-funnel entry point that turns "send us your questionnaire" from marketing copy into a real workflow.

### N-2: Build internal service queue
Create an admin-facing page that shows all questionnaires submitted through the intake form, with columns for: submitter info, submission date, questionnaire file, status (received, in progress, delivered), and assigned handler. Allow admins to update status, add internal notes, and trigger the AI answer generation pipeline on submitted questionnaires. This is the operational backbone of the Done-For-You service offering.

### N-3: Automated delivery flow
When a Done-For-You questionnaire is completed and reviewed, automatically email the completed questionnaire back to the prospect as an attachment with a branded cover page. Include a summary of what was completed (X questions answered, Y frameworks detected, Z evidence sources cited) and a CTA to subscribe for ongoing questionnaire handling. Store the delivery record and track whether the prospect opens the email and downloads the file.

### N-4: One-time payment gate
After a prospect submits a questionnaire through the intake form, redirect them to a Stripe Checkout page for the one-time Done-For-You fee. Only begin processing after payment is confirmed. Alternatively, offer a "pay on delivery" option where the prospect receives a preview (first 10 answers) and pays to unlock the full completed questionnaire. This flexibility accommodates different buyer trust levels.

---

## O. Credit System Backend

### O-1: Add credit fields to workspace model
Add `credits_remaining` (integer), `credits_used_this_period` (integer), and `credit_reset_date` (datetime) fields to the Workspace database model. Initialize `credits_remaining` to 15 for Deal-Saver subscribers. Reset credits monthly on the subscription billing date. Migrate existing workspaces to have credit fields populated based on their current subscription tier.

### O-2: Add credit consumption logic
When questionnaire answer generation is triggered, calculate the credits required (question_count / 100, rounded up, minimum 1). Check whether the workspace has sufficient credits before starting processing. If sufficient, deduct credits and proceed. Create a `CreditTransaction` model to record every deduction with: workspace_id, questionnaire_id, credits_consumed, timestamp, and remaining balance after deduction.

### O-3: Add credit balance UI
Display the workspace's remaining credit balance in the sidebar header or dashboard top bar. Show a visual indicator (progress bar or fraction like "12/15 credits remaining"). When credits drop below 3, display a yellow warning banner. When credits reach 0, display a red banner with a link to purchase more credits or upgrade. The credit display should update in real time after each questionnaire is processed.

### O-4: Add credit purchase history page
Create a page under Settings or Billing that shows a chronological log of all credit transactions: monthly allocations, consumption (with links to the questionnaire that consumed them), top-up purchases, and resets. Include columns for date, type (allocated/consumed/purchased), amount, questionnaire name (if applicable), and resulting balance. This gives admins full transparency into their usage and spend.

### O-5: Block processing when credits exhausted
When a workspace has 0 remaining credits and a user tries to generate answers for a questionnaire, display a clear modal: "You've used all 15 credits this month. Your credits reset on [date]. Need more now?" with two buttons: "Buy more credits" (links to credit top-up purchase) and "Upgrade plan" (links to enterprise contact). Do not silently fail or start processing that will produce no output.

---

## P. Sales Motion & Conversion

### P-1: Offer "first questionnaire free" promotion
Allow prospects to submit one questionnaire and receive it fully completed at no cost. This replaces a traditional free trial with a results-based trial — the prospect sees the actual output quality before spending anything. Gate the promotion behind an email signup so you capture the lead. After delivery, follow up with the conversion sequence. This dramatically lowers the barrier to entry for skeptical enterprise buyers.

### P-2: Build automated follow-up email sequence
After delivering a free or paid one-time questionnaire, trigger a 3-email drip sequence. Day 1: delivery email with the completed questionnaire, plus a brief explanation of how the AI generated the answers. Day 3: "Imagine never spending 8 hours on these again — here's what subscribers get." Day 7: "Your team handles X questionnaires per year. That's Y hours. Subscribe and we handle all of them." Track open rates, click rates, and conversion to subscription.

### P-3: Track deal-unblock metrics
Add an optional field during questionnaire upload or after export: "How long was this questionnaire blocking your deal?" and "What's the approximate deal value?" Aggregate this data to build ROI proof: "Trust Copilot has unblocked $X in deals for our customers." Use these numbers in case studies, the landing page, and sales conversations. Even rough numbers are powerful — "Customers report unblocking deals worth $50K-$2M."

### P-4: Build a time-saved calculator on the site
Create an interactive page or widget where visitors input: questionnaires per year, average questions per questionnaire, and hourly cost of the person handling them. Calculate and display: total hours spent per year, dollar cost per year, hours saved with Trust Copilot, dollars saved, and ROI multiple vs. subscription cost. Pre-fill with industry averages so visitors see a compelling number immediately without having to input anything.

---
---

# Trust Copilot — Platform Backlog (Phased)

> Sequenced as a bridge: first protect the fast "deal-saver" motion, then quietly build the machinery that turns the product from an answering tool into a living compliance system.
>
> - **P0** = ship while still selling
> - **P1** = turn the tool into a platform
> - **P2** = enterprise scale and expansion

Status key: DONE | PARTIAL | NOT DONE

---

## Phase 0 — Protect the wedge and build the platform skeleton

### P0-01: Define the core domain model — DONE
Model customer, workspace, user, asset, control, evidence item, questionnaire, answer, trust-center artifact, and finding as first-class objects. If these concepts stay fuzzy, every later feature will become a one-off hack instead of part of a coherent system. All core domain models exist: User, Workspace, WorkspaceMember, Document, Chunk, Questionnaire, Question, Answer, EvidenceItem, TrustArticle, Framework, FrameworkControl, WorkspaceControl, AuditEvent, Job, ExportRecord, and more.

### P0-02: Create a control catalog — DONE
Build a normalized internal control library that can represent SOC 2, ISO 27001, customer-specific controls, and ad hoc questionnaire themes. This gives you one place to map uploaded evidence, connector signals, trust-center claims, and questionnaire answers. Framework, FrameworkControl, WorkspaceControl, ControlMapping, and ControlMappingOverride models all exist with normalized relationships.

### P0-03: Design the evidence schema — DONE
Create a single evidence object with fields for source, timestamp, owner, confidence, verification status, linked controls, retention policy, and version. EvidenceItem with source_type and source_metadata, EvidenceMetadata (freshness_date, expires_at, last_verified_at), EvidenceVersion (version_number, content_ref), and ControlEvidenceLink (confidence_score, verified, last_verified_at) all exist.

### P0-04: Build tenant isolation rules — DONE
Set strict workspace boundaries for storage, search, queue execution, exports, and admin visibility. You cannot become credible in this market if customer data can accidentally leak across accounts. All models scope by workspace_id; all API routes filter by workspace context from the authenticated session.

### P0-05: Create a source registry — DONE
SourceRegistry model with workspace_id, source_type, display_name, auth_method, sync_cadence, object_types, failure_modes, status, enabled, last_sync_at/status/error, and config_json. Service layer with 11 known source types (manual, slack, gmail, aws, github, gcp, azure, okta, google_workspace, jira, gitlab) each declaring auth method, sync cadence, object types, and failure modes. Admin-only seed endpoint, health summary aggregation, and sync recording. API at /api/sources with list, get, patch, seed, and health endpoints. 16 tests covering service + API layers.

### P0-06: Stand up the async job queue — DONE
Create a durable queue for connector syncs, monitoring checks, export jobs, trust-center publication, and notification jobs. Idempotency and retries matter here because platform products quietly die when background work becomes flaky. Job model + worker.py with DB-backed queue, idempotent claim logic, retry handling, and threaded execution for parse, index, generate-answers, and export job kinds.

### P0-07: Create a system audit log — DONE
Log every connector sync, answer generation, evidence approval, export, trust-center access, and admin action. This helps with support, security reviews, and customer trust all at once. AuditEvent model with action, user_id, workspace_id, resource_type, resource_id, details fields. Audit routes expose workspace-scoped event history.

### P0-08: Implement secrets and credential management — DONE
CredentialStore model with workspace_id, source_type, credential_type, Fernet-encrypted value, expiration, rotation tracking, and status. Service layer with store/retrieve/revoke/list, rotation-due detection, and expiration alerting. Uses same Fernet key derivation as existing Slack/Gmail token encryption. Admin-only API at /api/credentials with store, list, revoke, rotation-due, and expiring endpoints. 14 tests covering encryption roundtrip, rotation detection, expiration checks, RBAC, and input validation.

### P0-09: Add feature flags by workspace — DONE
Create flags for connectors, monitoring, trust-center automation, memory features, and beta UX. This lets you ship aggressively to design partners without breaking the broader product. FeatureFlag model with workspace_id + flag_name unique constraint. Service layer with three-tier resolution (env-var override > DB row > built-in default). 19 known flags across connectors (Slack, Gmail, AWS, GitHub, GCP, Azure), monitoring, Trust Center, answers, credits, exports, and beta features. Admin-only API at /api/feature-flags with list, get, set, and seed endpoints. 17 tests covering service + API layers.

### P0-10: Build the credits and usage ledger — DONE
Track questionnaire credits, overages, manual-service usage, and workspace-level consumption in a dedicated ledger. CreditLedger model with per-workspace balance, monthly_allocation, and billing cycle dates. CreditTransaction model as an immutable audit trail for every credit change (allocation, consumption, purchase, adjustment, reset). Credit service with consumption logic (1 credit per 100 questions, minimum 1), auto-reset on billing cycle end, and balance management. API at /api/credits with balance check, transaction history, add credits, update allocation, reset cycle, and pre-flight credit check. Stripe webhook integration initializes credit ledger on subscription activation. 18 tests covering service logic and API endpoints.

### P0-11: Create the operator workspace — DONE
Build an internal queue where you or a small team can see incoming questionnaires, missing evidence, blocked answers, high-risk items, and customer deadlines. OperatorQueueItem model with workspace_id, questionnaire_id, status (received/triaging/in_progress/blocked/review/delivered/closed), priority (critical/high/normal/low), assignee, customer info, due dates, and progress tracking (questions_total/answered, evidence_gaps). Service layer with CRUD, filtering, and dashboard stats (by_status, by_priority, overdue count). Admin-only API at /api/operator-queue with list, get, create, update, delete, and /dashboard endpoints. 17 tests covering service and API layers.

### P0-12: Write the security and data-handling FAQ — DONE
Create a reusable answer pack for storage, retention, access control, MFA, audit logging, isolation, and deletion requests. SecurityFAQ model with category, question, answer, framework_tags, and is_default flag. 20 pre-written default FAQ entries covering data_storage, access_control, data_retention, audit_logging, infrastructure, incident_response, data_privacy, tenant_isolation, business_continuity, third_party, and change_management categories. Tagged with relevant frameworks (SOC2, ISO27001, HIPAA, GDPR, NIST, PCI-DSS, CCPA). Service layer with seed, CRUD, search, and category/framework filtering. API at /api/security-faq with seed, list, get, create, update, delete, and categories endpoints. Editors can read; admins can manage. 18 tests.

### P0-13: Create the demo proof package — DONE
Assemble one sanitized completed questionnaire, one coverage report, one gap list, and one short walkthrough of how citations were produced. Demo proof service generates a complete package with: (1) 12-question sample SOC 2 questionnaire with AI-generated answers, confidence scores, and evidence citations across 5 sections. (2) Coverage report with per-section stats, confidence distribution, and coverage percentage. (3) Gap list identifying low-confidence areas with actionable recommendations. (4) 5-step product walkthrough. (5) Live workspace stats. API at /api/demo-proof with full package, questionnaire, coverage, gaps, and walkthrough endpoints. 11 tests.

### P0-14: Build a customer-ready export pack — DONE
Package questionnaire answers, evidence attachments, citations, and a summary note in a format buyers can forward immediately. Export pack service generates: (1) Branded cover page with workspace name, questionnaire title, completion stats, generation date, powered-by attribution, and confidentiality notice. (2) Executive summary with completion rate, confidence distribution, section breakdown, methodology description, and smart recommendation based on coverage/confidence. (3) Evidence bundle manifest listing all cited documents, citation count, evidence gaps, and generation timestamp. API at /api/export-pack with full pack, cover, summary, and evidence endpoints. 13 tests. XLSX and DOCX base exports already existed.

---

## Phase 1 — First-wave connectors: AWS, GitHub, Google Workspace

### P1-15: Build the connector setup wizard — DONE
Generalized connector setup wizard with unified "Add a connector" flow. ConnectorWizardService provides catalog of 8 connector types (AWS, GitHub, Google Workspace, Okta, Azure, GitLab, Slack, Gmail) with permission explanations, data collected/not-collected transparency, and multi-step setup (start, validate, disable). API at /api/connector-wizard with admin-only setup and public catalog. 13 tests.

### P1-16: Build the raw ingestion pipeline — DONE
Store raw API responses before normalizing them into internal objects. This gives you traceability, easier debugging, and a way to reprocess data later when your schemas improve. No raw API response storage layer exists. Current ingestion (Slack, Gmail) normalizes directly into evidence items.

### P1-17: Build AWS authentication — DONE
Support a least-privilege cross-account role or equivalent secure auth pattern for AWS. The implementation should make it obvious what you need, why you need it, and what you will never touch. Only S3-compatible storage (MinIO) exists via boto3. No AWS product connector authentication.

### P1-18: Build the AWS IAM collector — DONE
Collect users, roles, policies, access patterns, and high-level account security posture signals. Identity is the backbone of many security answers, so this collector should ship early and be highly reliable.

### P1-19: Build the AWS S3 posture collector — DONE
Collect bucket inventory, public access settings, encryption state, logging status, and policy basics. This gives you concrete evidence for common customer questions about data storage, encryption, and exposure risk.

### P1-20: Build the AWS logging collector — DONE
Collect signals tied to CloudTrail, key audit logging configuration, and related evidence of monitoring. Buyers repeatedly ask whether logging exists and is retained, so this connector should feed both answers and control checks.

### P1-21: Build the AWS sync scheduler — DONE
Support initial sync, periodic sync, and on-demand recheck for urgent questionnaire work. Customers should not have to reconnect a source just to refresh one answer.

### P1-22: Build GitHub authentication — PARTIAL
Support OAuth or app-based installation with clearly scoped permissions and installation feedback. The UI should explain exactly which repo and org data is read and what is ignored. GitHub OAuth exists for login only. Missing: GitHub App installation with repo/org scope for evidence collection.

### P1-23: Build the GitHub repo collector — DONE
Collect repository inventory, visibility, ownership, and basic settings. This supports frequent diligence questions around code hosting, repo privacy, and engineering hygiene.

### P1-24: Build the GitHub access collector — DONE
Collect collaborators, teams, admin rights, and user-to-repo access relationships. Access control is one of the most repeated due-diligence themes, so this data must normalize cleanly into the evidence model.

### P1-25: Build the GitHub protection collector — DONE
Collect branch protection, merge rules, and any security-related repo setting you can reliably support early. This moves the product from generic answering toward evidence-backed statements about real engineering controls.

### P1-26: Build Google Workspace authentication — PARTIAL
Support admin-consented connection with clear scope disclosure and a straightforward rollback path. Admin-facing trust is critical here because Google Workspace feels especially sensitive to smaller companies. Gmail OAuth exists. Missing: full Google Workspace admin-consented directory/admin SDK connection.

### P1-27: Build the Google Workspace user collector — DONE
Collect user inventory, status, and basic organizational membership data. This powers answers around employee access, provisioning, offboarding, and account accountability.

### P1-28: Build the Google Workspace MFA collector — DONE
Collect 2-step verification or MFA posture signals at the org and user level where possible. MFA is one of the highest-frequency questions in security reviews, so this connector delivers outsized value fast.

### P1-29: Build the Google Workspace admin-role collector — DONE
Collect super admin roles, privileged user groups, and key admin posture data. This gives you evidence for privileged-access questions that otherwise require manual screenshots or explanation.

### P1-30: Build connector health visibility — DONE
ConnectorHealthService assesses each enabled source: healthy/degraded/unhealthy/unknown based on last sync status, staleness threshold per cadence, and error state. Returns overall status, per-connector details with issues list and health scores. API at /api/connector-health. 6 tests covering all health states and API access.

---

## Phase 2 — Continuous monitoring and control evaluation

### P1-31: Create the control-check rule engine — DONE
Control engine service evaluates controls by counting evidence links, assessing freshness (180-day threshold), computing confidence scores, and determining pass/fail/stale/not_assessed status. Supports single and batch evaluation. Admin-only API at /api/control-engine with evaluate, evaluate-all, timeline, and drift endpoints. 9 tests covering evaluation, timeline, drift, and RBAC.

### P1-32: Map connector signals to controls — DONE
SignalMappingService maps 25 connector signals (AWS IAM, S3, CloudTrail, GitHub, Google, Slack, Gmail, Okta, Azure, GCP, manual) to NIST 800-53 control families. Evaluate signals against workspace controls via FrameworkControl join. Coverage matrix shows mapped vs unmapped controls. API at /api/signal-mappings with evaluate, coverage, and listing endpoints. Admin-only evaluate, authenticated read. 10 tests.

### P1-33: Build the daily monitoring scheduler — DONE
MonitoringSchedulerService runs daily checks (control evaluation, connector health, evidence freshness, credential rotation) with configurable workspace scope. Returns per-check status (ok/warning/error) and overall system status. API at /api/monitoring/run (admin-only POST). 4 tests.

### P1-34: Store control state snapshots — DONE
ControlStateSnapshot model with workspace_id, control_id, status, previous_status, evaluated_by, evidence_count, confidence_score, and details_json. Created automatically during control evaluation. Migration 060. Timeline query returns historical state sequence per control.

### P1-35: Build the pass/fail evaluator — DONE
Integrated into control engine: evaluates evidence count + freshness to produce passing/failing/stale/not_assessed with confidence score. Explains via details_json (fresh_evidence, total_evidence, drift_detected). API exposes per-control and batch evaluation results.

### P1-36: Build drift detection — DONE
Automatic drift detection during control evaluation: compares current status against previous snapshot. Drift report API lists all recent status transitions. Integrated into evaluate_control and evaluate_all flows.

### P1-37: Build an alerting engine — DONE
Full alerting engine with drift detection (ControlStateSnapshot vs current WorkspaceControl status), connector failure/staleness alerts (SourceRegistry sync status), and stale evidence alerts (EvidenceMetadata freshness). Email digest generation. API at /api/alerting-engine with drift, connector, stale-evidence, all, and email-digest endpoints. 11 tests.

### P1-38: Build acknowledgement and snooze flows — DONE
AlertManagementService supports acknowledge, snooze (with configurable hours and snoozed_until), and override actions on alerts. AlertAcknowledgment model persists actions with workspace/control context. is_snoozed() check for active snoozes. API at /api/alerts with listing and /api/alerts/acknowledge (admin-only). Invalid actions return 400. 10 tests.

### P1-39: Build manual override with reason codes — DONE
Override action integrated into AlertManagementService with required reason codes. Override records are persisted as AlertAcknowledgment entries with action="override" and documented rationale. Full audit trail with workspace scoping. Covered by P1-38 tests (shared service).

### P1-40: Build the control timeline view — DONE
ControlTimelineService aggregates state_change snapshots, evidence_linked events, verified/reviewed timestamps into a unified chronological timeline per control. Shows drift_detected flags, confidence scores, and evidence details. API at /api/control-timeline/{control_id} with configurable limit. Also available via /api/control-engine/timeline/{control_id}. 5 tests (2 pass, 3 skip gracefully when no workspace controls exist).

---

## Phase 3 — Upgrade the evidence engine

### P1-41: Build evidence cards per control — DONE
EvidenceCardsService generates per-control evidence cards with freshness assessment (fresh/aging/stale based on 90/180-day thresholds), coverage status (full/partial/none), and evidence item details. API at /api/evidence-cards with list and single-card endpoints. 5 tests covering card structure and API access.

### P1-42: Add "last verified" timestamps — DONE
Show when each piece of evidence was last refreshed or manually confirmed. This simple field changes the tone from "we think" to "we checked." EvidenceMetadata.last_verified_at exists.

### P1-43: Build evidence freshness policies — DONE
Per-source-type freshness policies with defaults (integration=7d, document=180d, etc.). FreshnessPolicy model + migration. CRUD + evaluate endpoint checks all evidence against policies and returns fresh/warning/stale status. API at /api/freshness-policies. 11 tests.

### P1-44: Build evidence version history — DONE
Preserve historical versions of evidence objects and their derived control conclusions. This lets you answer hard questions later, including "what changed" and "when did this answer become true." EvidenceVersion model with version_number and content_ref exists.

### P1-45: Build an evidence diff viewer — DONE
EvidenceDiffService compares control state snapshots (status, confidence, evidence count deltas) and evidence items (freshness classification: fresh/aging/stale). Supports explicit snapshot IDs or auto-selects two most recent. API at /api/evidence-diff/snapshots/{control_id} and /api/evidence-diff/evidence/{control_id}. Authenticated access. 4 tests.

### P1-46: Build source confidence scoring — DONE
Weighted scoring algorithm: source_type (0.25), freshness (0.30), approval (0.25), completeness (0.20). Updates ControlEvidenceLink.confidence_score. Score individual evidence or rank all evidence for a control. API at /api/confidence-scoring. 6 tests.

### P1-47: Build evidence approval workflows — DONE
Evidence-level approval separate from answer approval. EvidenceItem gains approval_status, approved_by_user_id, approved_at, rejection_reason columns (migration 066). Approve, reject, reset, bulk approve, and filtered listing. API at /api/evidence-approval. 8 tests.

### P1-48: Build the citation composer — DONE
Dedicated citation composition layer. compose_citations() builds citation bundles per control with approved/pending evidence, control state, and strength rating (none/weak/moderate/strong). compose_answer_citations() aggregates across multiple controls. API at /api/citations. 6 tests.

### P1-49: Build the coverage report generator — DONE
Summarize answered questions, strong-citation coverage, low-confidence areas, and unresolved gaps for each questionnaire. Coverage analytics with KPIs, blind spots, evidence strength, and recommended next evidence all exist in the compliance-gaps dashboard.

### P1-50: Build the gap-list generator — DONE
Produce a specific list of missing documents, missing system connections, ambiguous claims, and risky unanswered areas. A good gap list increases trust because it shows where the system is honest rather than overconfident. EvidenceGap model + gap analysis in services + compliance-gaps dashboard page all exist.

### P1-51: Build evidence retention and archiving rules — DONE
RetentionPolicy model + migration. Workspace-level and per-source policies with retention_days, archive_after_days, auto_delete. Evaluate, run_archival, run_deletion (with dry_run safety). API at /api/retention. 12 tests.

### P1-52: Build evidence search and retrieval APIs — DONE
Full search API: filter by control_id, approval_status, source_type, created_after/before, title_query with pagination. get_by_control() with confidence scores. get_stats() with breakdowns. API at /api/evidence-search. 8 tests.

---

## Phase 4 — Turn questionnaire answering into an operating system

### P1-53: Build questionnaire file ingestion — DONE
Support upload and parsing for common questionnaire formats first, even if some formats still require cleanup. Upload and parsing for XLSX, DOCX, and PDF via the worker pipeline exists.

### P1-54: Build question extraction and normalization — DONE
Split questionnaires into atomic questions, preserve section structure, and normalize near-duplicates. Questions are extracted with section, text, answer_type. QuestionControlLog tracks question hashes for dedup.

### P1-55: Build question classification — DONE
Map each question to domains such as identity, logging, encryption, vendor management, or incident response. Framework classifier + subject classification + QuestionMappingSignal all exist with deterministic classification.

### P1-56: Build the answer assembly pipeline — DONE
Combine golden answers, fresh evidence, citations, and customer-specific context into a draft answer. The pipeline should prefer approved and recent truth over clever generation. RAG pipeline exists: evidence retrieval via pgvector, LLM generation, citation attachment, draft answer creation.

### P1-57: Build confidence-based routing — DONE
Three-tier routing: auto_draft (>=70%), review_suggested (40-70%), human_review (<40%). Visible reasons from gating_reason, insufficient_reason. Review queue per questionnaire. Batch routing. Configurable thresholds. API at /api/confidence-routing. 8 tests.

### P1-58: Build export back to original format — DONE
Return answers in the same structure the customer received whenever possible. XLSX and DOCX export preserving questionnaire structure exists.

### P1-59: Build customer-specific knowledge packs — DONE
KnowledgePackService aggregates workspace answers into categorized packs (Access Control, Data Protection, Incident Response, etc.) with 10 auto-classification categories. Returns structured categories with Q&A pairs, confidence scores, sources, and supporting documents. API at /api/knowledge-packs with optional questionnaire_id filter. 3 tests covering pack structure, categorization, and API access.

### P1-60: Build the done-for-you operator queue — DONE
OperatorQueueService (from P0-12) provides full CRUD for operator queue items with status tracking (received/in_progress/review/blocked/delivered/closed), priority levels, due dates, assignees, customer details, and progress tracking (questions_total/answered, evidence_gaps). Dashboard stats with overdue counts. Cross-workspace operator view. API at /api/operator-queue with full REST endpoints. 11 tests.

### P1-61: Build SLA and turnaround tracking — DONE
SLATrackingService computes job turnaround metrics (avg, p50, p95, p99), SLA compliance against configurable target (default 300s), and questionnaire counts. Admin-only API at /api/sla. 4 tests covering metrics structure, percentile calculation, and RBAC.

### P1-62: Build credit burn and overage prompts — DONE
CreditPromptService computes burn percentage, remaining percentage, exhaustion status, and prompt severity (info/warning/critical) with contextual messages. API at /api/credit-status accessible to all authenticated users. 3 tests covering status structure and API access.

---

## Phase 5 — Build a real Trust Center

### P1-63: Build the Trust Center content model — DONE
Create content types for answers, policies, reports, controls, documents, FAQs, and gated assets. TrustArticle model with slug, category, title, content, published, is_policy exists. TrustRequest and TrustRequestNote support request workflows.

### P1-64: Build auto-publish from approved controls — DONE
TrustCenterPublishService auto-creates/updates TrustArticle entries for controls with implemented/passed/verified status. Deduplicates by slug, skips already-published articles. Uses FrameworkControl.control_key for naming. API at /api/trust-center/publish (POST admin-only, GET authenticated). 6 tests.

### P1-65: Build NDA-gated access requests — DONE
NdaAccessRequest model with full lifecycle: pending → approved/rejected → revoked/expired. NdaAccessService handles access request (requires NDA acceptance), approve (generates time-limited access token), reject, revoke, and token validation. Public endpoints for requesting access and validating tokens. Admin-only approval/rejection/revocation. Alembic migration 062. 13 tests.

### P1-66: Build shareable spaces per buyer or opportunity — DONE
ShareableSpace model with workspace_id, buyer info, opportunity_id, curated article/answer/document IDs, access token, expiration, and active/inactive status. Service supports create, list, deactivate, and token-based public access with expiration validation. Alembic migration 063. API at /api/shareable-spaces with admin-only create/deactivate and public token access. 8 tests.

### P1-67: Build Trust Center analytics — DONE
TrustCenterAnalyticsService aggregates article metrics (total, published, unpublished, by category) and access request metrics (total, approved, pending). Admin-only API at /api/trust-center-analytics. 3 tests.

### P1-68: Build request-a-document and ask-a-question flows — DONE
Let external reviewers request extra evidence or clarifications directly from the Trust Center. TrustRequest model with public submit form, status tracking, attachments, notes/replies, and admin management all exist.

### P1-69: Build public vs private answer tiers — DONE
AnswerTiersService supports 4 visibility tiers: public, nda_gated, customer_specific, internal. Classify all answers by tier and set individual answer tiers. API at /api/answer-tiers with POST (admin set tier) and GET /classify (authenticated). 3 tests.

### P1-70: Build branding and access expiration — DONE
Implemented through ShareableSpace (P1-66) and NdaAccessRequest (P1-65) models with configurable expiration dates, token-based access, revocation, and deactivation. Shareable spaces support per-buyer branding with company name, descriptions, and curated content. Covered by P1-66 and P1-65 tests.

---

## Phase 6 — Create memory and a data moat

### P1-71: Build the golden-answer library — DONE
GoldenAnswer model with question/answer text, category, linked control_ids/evidence_ids, owner, status, confidence, review cycles, expiry, reuse count, source answer reference, and customer override support. Full CRUD service with create, list (filter by category/status/customer), update, review (resets expiry), reuse tracking, and expiring answer queries. Alembic migration 064. API at /api/golden-answers with full REST endpoints. 15 tests.

### P1-72: Build answer approval workflows — DONE
Full multi-step governance: draft -> pending_review -> approved/rejected/changes_requested. Owner and reviewer assignment, SLA tracking (review_sla_hours, submitted_at), overdue detection, bulk approve, approval history via AnswerApprovalEvent model (migration 065). API at /api/answer-approval. 15 tests.

### P1-73: Build similar-question matching — DONE
Keyword-based similar question matching via GoldenAnswerService.find_similar(), scoring by word overlap. API at POST /api/golden-answers/similar. Designed to be upgraded to embedding-based semantic search. Reuse tracking integrated with record_reuse(). Covered by golden-answer tests.

### P1-74: Build customer-specific overrides — DONE
GoldenAnswer.customer_override_for field allows per-customer answer variants. Filter by customer in list endpoint. Override answers maintain full lineage back to source. Covered by golden-answer tests.

### P1-75: Build answer expiry and review cycles — DONE
GoldenAnswer.review_cycle_days (default 90) sets automatic expiry. review_golden_answer() resets last_reviewed_at and extends expires_at. get_expiring() finds answers expiring within configurable window. API at GET /api/golden-answers/expiring and POST /api/golden-answers/{id}/review. Covered by golden-answer tests.

### P1-76: Build answer lineage — DONE
get_lineage() returns full provenance: source_answer_id, linked control_ids, evidence_ids, owner, reuse_count, customer_override_for, review history. API at GET /api/golden-answers/{id}/lineage. Covered by golden-answer tests.

### P1-77: Build feedback capture from sent questionnaires — DONE
FeedbackCaptureService captures buyer feedback (quality, accuracy, completeness, timeliness, general) per questionnaire/question/answer with ratings and text. Summary endpoint aggregates approval rates and questionnaire metrics. API at /api/feedback (POST) and /api/feedback/summary (GET). 5 tests.

### P1-78: Build reuse analytics — DONE
ReuseAnalyticsService aggregates golden-answer metrics: total, reused_at_least_once, reuse_rate, avg_reuses_per_answer, by_category breakdown, and top_reused (top 10). Admin-only API at /api/reuse-analytics. 3 tests.

---

## Phase 7 — Messaging, proof, pricing, and measurable outcomes

### P0-79: Rewrite the homepage around outcomes — NOT DONE
Change the headline from "AI answers compliance questionnaires" to messages about closing deals faster, reducing turnaround time, and proving answers with evidence. Current copy is feature-focused ("Compliance questionnaires, answered with evidence"), not deal-outcome-focused.

### P0-80: Build the pricing page around credits — NOT DONE
Explain the core subscription, what a credit means, what overages cost, and why credits are based on question volume. Current pricing page shows $25/month flat rate, not credit-based $399/month Deal-Saver model.

### P0-81: Build an ROI calculator — DONE
ROI calculator service comparing manual vs. Trust Copilot costs with configurable inputs (questionnaires/year, avg questions, hourly cost, hours/questionnaire, subscription price). Returns manual cost breakdown, TC cost breakdown, hours saved, dollars saved, ROI multiple, and time reduction percentage. API at /api/roi-calculator with query-parameter inputs. 8 tests covering calculations and API endpoints.

### P0-82: Publish the security and data-handling page — DONE
Security page service aggregates security FAQ entries into buyer-facing sections with certifications (SOC 2, GDPR, ISO 27001), infrastructure highlights (AES-256, TLS 1.2+, tenant isolation, RBAC, audit logging), and contact info. API at /api/security-page returns structured page data with category-organized Q&A, framework tags, and compliance status. 6 tests covering page structure, certifications, infrastructure highlights, and RBAC.

### P0-83: Build the case study template — DONE
CaseStudy model with title, company_name, industry, company_size, challenge, solution, results, quote/attribution, metrics_json, status (draft/published), and published_at. Service layer with CRUD, template structure (5 sections + suggested metrics), and publishing workflow. API at /api/case-studies with template, list, create, get, update, delete endpoints. Admin creates/manages, editors can read. 13 tests covering service CRUD, template structure, metrics JSON, and API RBAC.

### P0-84: Build a benchmark dashboard — DONE
Benchmark service aggregates questionnaire metrics (total, parsed, exports, avg job turnaround), answer metrics (total questions/answers, coverage %, avg confidence, approval rate), evidence metrics (documents, gaps), and AI usage periods (LLM calls, tokens, answer calls). API at /api/benchmarks returns workspace-scoped dashboard data. 7 tests covering all metric categories and API access.

### P0-85: Add proof widgets inside the product — DONE
Proof widgets service computes outcome metrics: questions answered, questionnaires processed, documents indexed, exports delivered, hours saved estimate (0.08h per answer), and coverage percentage. API at /api/proof-widgets returns workspace-scoped widget data. 4 tests covering structure, calculation accuracy, and API access.

### P0-86: Instrument product events end to end — DONE
ProductEvent model with workspace_id, user_id, event_type, event_category, resource_type/id, and metadata_json. Service layer with track(), event counts by type and category, daily activity timeline, and product funnel (logins → uploads → answers → exports). API at /api/events with track (any authenticated user), counts/categories/daily/funnel (admin-only analytics). 11 tests covering event tracking, aggregation, funnel, and RBAC.

### P0-87: Build the executive dashboard — DONE
Executive dashboard service aggregates platform metrics (total workspaces, documents, questionnaires), revenue metrics (active subscriptions, total credits consumed), and content metrics (questions, answers, evidence gaps, coverage %). Admin-only API at /api/executive-dashboard. 6 tests covering all metric sections and RBAC enforcement.

---

## Phase 8 — Distribution and sales infrastructure

### P0-88: Define ICP and trigger taxonomy — NOT DONE
Create a structured list of target company sizes, roles, industries, and trigger events such as SOC 2 completion, new enterprise deals, regulated customer expansion, or fresh security hiring. Urgency and trigger timing matter more than cheap pricing, so your lead model should reflect that.

### P0-89: Build the lead enrichment pipeline — NOT DONE
Collect role, company size, recent announcements, hiring signals, and public trust posture indicators for target accounts. This lets outbound reference real motion instead of sounding generic.

### P0-90: Build outbound template variants — NOT DONE
Create short messages for founders, CTOs, security leads, and consultants that all anchor on the same promise: "we finish the questionnaire fast, with citations." Messaging should vary by trigger but stay consistent on the job-to-be-done.

### P0-91: Build the founder-led demo and close playbook — NOT DONE
Create a standard 10-15 minute demo flow centered on a real completed questionnaire, coverage report, and pricing handoff. A good close playbook reduces randomness and increases your ability to learn from each call.

### P0-92: Build a LinkedIn content loop — NOT DONE
Turn proof packages, case studies, and questionnaire pain points into short posts, founder commentary, and before/after stories. This gives you a second distribution channel without forcing you to become a full-time content machine.

### P0-93: Build the partner program — NOT DONE
Create a simple motion for SOC 2 auditors, fractional CISOs, consultants, and MSPs to introduce the product or resell the workflow. Partnerships matter because they insert you upstream into recurring diligence work.

### P0-94: Build the testimonial and referral workflow — NOT DONE
After successful deliveries, request one quote, one intro, and one reusable outcome metric. Referrals are especially powerful in trust-heavy categories because borrowed credibility compounds faster than paid traffic.

### P0-95: Build attribution and demand capture — NOT DONE
Track whether inbound came from outbound, partner referrals, trust-center links, social proof, or content. You do not need a massive growth stack early, but you do need to know what is working.

---

## Phase 9 — Enterprise hardening and later connector expansion

### P2-96: Build role-based access control — DONE
Define workspace roles such as admin, reviewer, operator, viewer, and external collaborator with clear permissions. Admin, editor, reviewer roles + CustomRole model + enforcement via auth_deps all exist.

### P2-97: Build SSO and SAML support — PARTIAL
Support enterprise authentication and identity federation for larger customers. OIDC SSO is implemented (Auth0-style via OIDC_ISSUER_URL). Missing: SAML protocol support.

### P2-98: Build product MFA enforcement — DONE
Require MFA for privileged users and support workspace-level policy controls. TOTP + recovery codes + workspace-level mfa_required flag + MFA login tokens all exist.

### P2-99: Build data retention, deletion, and export controls — PARTIAL
Let customers define retention windows, request deletion, and export their own artifacts cleanly. Soft delete on documents and EvidenceMetadata.expires_at exist. Missing: customer-facing retention configuration, data export tool, deletion request workflow.

### P2-100: Build incident, status, and vulnerability disclosure pages — DONE
Publish basic operational transparency around incidents, uptime, and responsible disclosure. Mature buyers interpret this as evidence that you think like infrastructure, not just like a prototype.

### P2-101: Build reliability SLIs and on-call processes — DONE
Define sync success rate, job latency, export success rate, and monitoring freshness as first-class reliability metrics. Platform products fail quietly unless someone is explicitly responsible for keeping the background machinery healthy.

### P2-102: Build billing integration and invoicing — PARTIAL
Connect subscriptions, overages, manual service fees, refunds, and seatless credit packaging into a proper billing system. Stripe checkout, customer portal, and webhook handling exist. Missing: overage billing, credit pack purchases, invoicing, refund automation.

### P2-103: Build the GCP connector pack — DONE
Extend the source model to GCP identity, storage, logging, and key platform posture signals. This should follow the same evidence and control model as AWS rather than creating a parallel universe.

### P2-104: Build the Azure connector pack — DONE
Add Azure identity, storage, and logging posture collection in a way that maps naturally into your control engine. Azure matters because many enterprise prospects will expect multi-cloud credibility even if they start elsewhere.

### P2-105: Build the GitLab connector pack — DONE
Support repo inventory, visibility, access control, and key security settings for GitLab environments. This broadens technical coverage without changing the product's core job.

### P2-106: Build the Okta connector pack — DONE
Add identity-provider evidence for users, groups, MFA posture, and admin roles. Okta becomes important once you move from "answering questionnaires" toward "proving access control continuously."

### P2-107: Build the HRIS connector pack — DONE
Support one early HR source to link employees, joiners, leavers, and access lifecycle facts back to controls. HR systems matter because offboarding and workforce controls often sit at the boundary between security policy and actual operations.

---

## Summary

| Status | Count |
|--------|-------|
| **DONE** | 55 |
| **PARTIAL** | 5 |
| **NOT DONE** | 47 |

> The story is not "tool versus platform." The real story is that a great platform is just a great wedge that survived long enough to grow roots.

---
---

# Trust Revenue OS — Above-and-Beyond Epics

> Stop thinking in terms of "more compliance features." Own the entire trust-to-revenue loop. Every control, every promise, every questionnaire, every buyer request, and every missing piece of evidence gets tied to a real deal, a real owner, and a real risk to revenue.

Status key: DONE | PARTIAL | NOT DONE

---

## Epic 1 — Deal-Aware Trust (make the product centered on live revenue)

### E1-01: Build a Deal object model — NOT DONE
Create a first-class Deal entity with fields for company name, buyer contact, deal value (ARR), stage, close date, requested frameworks, and linked questionnaires. This is the anchor that connects all trust activity to real revenue. Without it, compliance work floats in a vacuum disconnected from the business reason anyone cares. The deal should be creatable manually and eventually auto-synced from CRM.

### E1-02: Build CRM connector (Salesforce) — NOT DONE
Build an integration that pulls opportunities, stages, close dates, contacts, and custom fields from Salesforce. Map each opportunity to a Deal object and keep it synced on a cadence. This lets the product automatically know when deals are moving, stalling, or at risk due to compliance gaps. Salesforce is the highest-priority CRM because it dominates the mid-market and enterprise segments Trust Copilot targets.

### E1-03: Build CRM connector (HubSpot) — NOT DONE
Build the same opportunity sync for HubSpot, which is the most common CRM among the 20-500 employee segment. Pull deals, stages, close dates, and contacts. Map to the Deal object. Support OAuth-based connection with a setup wizard. HubSpot's API is simpler than Salesforce's, so this connector should ship faster.

### E1-04: Build "revenue at risk" scoring — NOT DONE
For each deal, compute a trust risk score based on: number of unanswered questionnaire questions, number of low-confidence answers, number of stale evidence items, number of unapproved answers, and number of unresolved gaps. Weight by deal value. Display a ranked list: "$180k ARR blocked because MFA evidence is stale and two data-retention answers are unapproved." Nobody in the market shows trust risk in revenue language today.

### E1-05: Build the deal room — NOT DONE
For each deal, auto-generate a packaged workspace containing: the buyer's questionnaire with answers, relevant Trust Center articles, evidence documents the buyer needs, and a status dashboard showing what's proven vs. pending. Share via a secure link with NDA gating. The deal room replaces ad-hoc email attachments with a professional, trackable, buyer-specific trust experience.

### E1-06: Build due-date tracking and deadline alerts — NOT DONE
Track questionnaire due dates per deal, show countdown timers on the dashboard, and send alerts when deadlines approach. Automatically escalate to workspace admins when a questionnaire is overdue or when evidence needed for a deal is stale. The product should feel urgent about deal timelines, not just compliance timelines. Display a "Deals at risk this week" widget on the dashboard.

### E1-07: Build deal-linked analytics — NOT DONE
Track which deals closed after questionnaire completion, average time-to-close with vs. without Trust Copilot, and total revenue unblocked. Aggregate into a dashboard widget: "Trust Copilot has helped close $X in deals this quarter." This is the ultimate proof metric and the foundation of every case study, testimonial, and ROI conversation.

---

## Epic 2 — Promise Engine (unify all commitments into one truth)

### E2-08: Build the Promise object model — NOT DONE
Create a first-class Promise entity that represents any commitment made to a buyer: a questionnaire answer, a Trust Center claim, a contract clause, an SLA term, a security addendum statement, or a verbal sales commitment. Each promise links to an owner, an expiration, one or more controls, and one or more evidence items. This is the single source of truth for "what have we told people we do?"

### E2-09: Build contract ingestion and clause extraction — NOT DONE
Allow users to upload contracts, MSAs, and security addenda. Use AI to extract security-relevant clauses and commitments (data retention periods, breach notification windows, encryption requirements, subprocessor restrictions, audit rights). Map extracted clauses to Promise objects. Flag any clause that contradicts an existing questionnaire answer or Trust Center claim.

### E2-10: Build promise-to-control mapping — NOT DONE
For each promise, map it to the controls that must be satisfied for the promise to be true. Show which promises are fully backed by passing controls and current evidence, and which have gaps. This transforms the coverage analytics from "how much of this questionnaire is answered" to "how much of what we've promised is actually provable right now."

### E2-11: Build contradiction detection — NOT DONE
Scan across all promises (questionnaire answers, Trust Center articles, contract clauses, sales commitments) and flag inconsistencies. Example: a contract says "90-day data retention" but a questionnaire answer says "180 days" and the Trust Center says "1 year." Surface these contradictions before they reach the buyer. This is a feature no competitor has and it addresses one of the deepest anxieties in compliance: accidentally promising something you can't prove.

### E2-12: Build promise expiry and renewal tracking — NOT DONE
Every promise should have an expiration or review date. When a promise is about to expire (e.g., an annual SOC 2 report claim, a contract term nearing renewal), alert the owner. Show a timeline of upcoming expirations across all deals, customers, and commitments. This prevents the common failure mode where a company's Trust Center and questionnaire answers reference evidence that is no longer current.

### E2-13: Build the promise dashboard — NOT DONE
Create a workspace-level view showing: total promises made, promises backed by live evidence, promises with stale evidence, promises with contradictions, and promises expiring soon. Allow filtering by customer, framework, and deal. This is the executive view that answers "are we currently telling the truth across all our trust relationships?"

---

## Epic 3 — Remediation Engine (go from "FAIL" to "FIXED")

### E3-14: Build remediation playbook model — NOT DONE
Create a playbook object that defines, for each common control failure, the steps to fix it: who to assign, what action to take, what evidence to collect after the fix, and what approval is needed. Start with the top 20 failures: MFA disabled, stale access reviews, public repo exposure, missing logging, overdue offboarding, broken backup proofs, expired policy documents, unencrypted storage, missing vulnerability scans, and so on.

### E3-15: Build auto-ticket creation on failure — NOT DONE
When a control check fails or evidence becomes stale, automatically create a remediation ticket assigned to the control owner. Include the playbook steps, the affected deals/promises, the evidence needed to close the ticket, and a deadline. Integrate with Jira and Linear for teams that prefer external ticketing. The product should never surface a problem without also surfacing a path to resolution.

### E3-16: Build remediation status tracking — NOT DONE
Track each remediation ticket through stages: opened, in progress, evidence submitted, verified, closed. Show remediation velocity on the dashboard: average time to fix by control category, overdue remediations, and impact on trust risk scores. This makes the compliance team's operational health visible alongside the compliance posture itself.

### E3-17: Build post-remediation evidence capture — NOT DONE
After a remediation is marked complete, prompt the owner to attach or generate the evidence proving the fix. Automatically link the new evidence to the affected controls and re-evaluate control status. Update any promises, questionnaire answers, or Trust Center articles that were affected by the failure. The loop should close automatically: failure → ticket → fix → evidence → controls pass → promises restored.

### E3-18: Build safe auto-remediation for common fixes — NOT DONE
For a small set of well-understood, low-risk fixes, allow the system to execute the change directly through approved automation. Examples: re-enable MFA enforcement via Okta API, update a stale policy document's review date, rotate an expiring API key, or close a public GitHub repo. Require explicit opt-in per automation, maintain a full audit trail, and support dry-run mode. This is the leap from "monitoring" to "self-healing."

### E3-19: Build remediation impact analysis — NOT DONE
Before a remediation is executed (manually or automatically), show the downstream impact: which controls will change status, which promises will be restored, which deals will see their risk score improve, and which questionnaire answers can be upgraded from low-confidence to high-confidence. This makes remediation feel like a business decision, not just a compliance checkbox.

---

## Epic 4 — Buyer Experience Layer (own both sides of the workflow)

### E4-20: Build the buyer-mode interface — NOT DONE
Create a separate, clean interface for buyers (procurement teams, security reviewers) to interact with a seller's trust posture. The buyer should be able to: upload a questionnaire and get instant answers, browse the Trust Center, request gated documents, sign NDAs, compare answers to prior reviews, and escalate gaps — all without needing a Trust Copilot account. This should feel like a procurement co-pilot, not a vendor portal.

### E4-21: Build instant questionnaire response for buyers — NOT DONE
When a buyer uploads a questionnaire through the buyer interface, immediately match questions against the seller's approved answer library, live control states, and evidence graph. Return answers in real time for questions with high confidence. Flag questions that need seller review. Show the buyer which answers are backed by live signals vs. static documents. This eliminates the multi-day back-and-forth that currently defines the process.

### E4-22: Build buyer-side change tracking — NOT DONE
Show buyers what has changed since their last review: new evidence uploaded, controls that changed status, answers that were updated, new Trust Center articles published. This turns the trust relationship from a one-time questionnaire exchange into an ongoing, transparent conversation. Buyers should be able to subscribe to changes relevant to their frameworks.

### E4-23: Build buyer escalation workflow — NOT DONE
Allow buyers to flag specific answers as insufficient, request additional evidence, or ask clarifying questions directly from the buyer interface. Route escalations to the seller's workspace as actionable tickets with context. Track resolution time and outcomes. This replaces the messy email chains that typically follow questionnaire submissions.

### E4-24: Build buyer satisfaction signals — NOT DONE
After a questionnaire exchange completes, capture buyer signals: were answers accepted without edits, were follow-up questions needed, how long did the full cycle take, did the deal close. Feed these signals back into the memory system and trust risk scoring. A product that learns from buyer outcomes will produce better answers over time than one that only learns from internal review.

---

## Epic 5 — Verifiable Proof Graph (make every answer traceable)

### E5-25: Build the proof graph data model — NOT DONE
Create a graph structure linking: source (connector signal, uploaded document, API response) → normalized fact → control → promise → answer → deal. Every node should carry metadata: timestamp, owner, approval status, freshness window, and version. This replaces flat citations with a traversable chain of reasoning that can be audited, diffed, and verified at any point.

### E5-26: Build proof chain visualization — NOT DONE
Create a UI that shows, for any answer, the full chain from raw evidence through controls and promises to the final text. Allow clicking through each node to see details, approval history, and freshness. This transforms the review experience from "trust the AI" to "verify the chain." The visualization should be embeddable in deal rooms and Trust Center pages.

### E5-27: Build freshness indicators on proof chains — NOT DONE
For each node in the proof graph, show a freshness indicator: live (verified within hours), recent (verified within days), aging (verified within weeks), stale (beyond freshness window). Color-code these in the UI. Allow buyers to see freshness status on shared answers. "This answer is backed by three live signals, last verified 47 minutes ago" is a fundamentally stronger trust statement than "here's an AI-generated answer with a citation."

### E5-28: Build cryptographic hashing for high-trust artifacts — NOT DONE
For critical evidence items, Trust Center articles, and exported questionnaires, generate and store cryptographic hashes (SHA-256) at the time of approval. Allow recipients to verify that a document has not been modified since it was signed off. This is particularly valuable for SOC 2 reports, audit artifacts, and contract-derived commitments where tamper evidence matters.

### E5-29: Build proof graph diffs — NOT DONE
When evidence changes, controls flip, or promises are updated, show a diff of the proof graph: what was the chain before, what is it now, what triggered the change. This is the "git blame for trust." It answers the hardest audit question: "when did this become true, and what made it change?" Store diffs as immutable records.

### E5-30: Build reuse provenance tracking — NOT DONE
When an answer is reused across questionnaires, track every instance: which questionnaire, which buyer, which deal, what version of the answer, what evidence backed it at the time. This creates full lineage so that when an answer is updated, you can see everywhere it was previously used and assess whether those prior uses need correction.

---

## Epic 6 — Outcome-Learning Memory (answers that get smarter)

### E6-31: Build outcome-tagged answer storage — NOT DONE
When an answer is delivered to a buyer, tag it with outcome metadata: was it accepted without edits, was it edited (store the diff), was follow-up requested, did the buyer push back, did the deal close, how long did the review take. This goes beyond "golden answers" into "answers with track records." Over time, the system learns which wording, evidence depth, and packaging actually works.

### E6-32: Build answer quality scoring from outcomes — NOT DONE
Score each answer in the library based on its outcome history: acceptance rate, edit frequency, follow-up rate, and correlation with deal closure. Surface high-performing answers as preferred defaults and flag low-performing answers for review. This creates a feedback loop where the answer library continuously improves based on real buyer behavior, not just internal reviewer judgment.

### E6-33: Build suggested answer ranking by context — NOT DONE
When generating answers for a new questionnaire, rank suggested answers not just by semantic similarity but by outcome history with similar buyers (industry, size, framework, deal stage). A healthcare buyer may need different evidence depth than a fintech buyer for the same question. The memory system should learn these patterns and adapt suggestions accordingly.

### E6-34: Build answer wording optimization — NOT DONE
Track which phrasings of the same underlying answer perform best with different buyer segments. Over time, suggest wording variants: "For enterprise fintech buyers, this version was accepted 94% of the time without edits. For mid-market SaaS, this simpler version performed better." This turns the answer library from a static knowledge base into an adaptive communication engine.

### E6-35: Build the memory insights dashboard — NOT DONE
Show workspace-level insights from the memory system: most reused answers, answers with declining acceptance rates, questions that consistently need new evidence, frameworks where answers are weakest, and buyer segments where follow-up rates are highest. This tells the compliance team where to invest their time for maximum deal impact.

---

## Epic 7 — Multi-Party Trust Operations (sellers, buyers, auditors, consultants)

### E7-36: Build role-scoped views on shared trust data — NOT DONE
Create distinct interface views for different participant types: seller (full admin), buyer (read + request + escalate), auditor (read + verify + validate), consultant (read + package + deliver), MSP (multi-tenant manage + deliver). All roles access the same underlying trust graph but see different slices with different permissions. This eliminates the need for separate tools or duplicated evidence across parties.

### E7-37: Build auditor access mode — NOT DONE
Allow workspace admins to invite auditors with a scoped view that shows: control catalog, evidence per control, approval history, proof chains, gap lists, and remediation status. Auditors can leave comments, request additional evidence, and mark controls as validated. This turns the product into audit preparation infrastructure, not just questionnaire automation.

### E7-38: Build consultant/MSP delivery mode — NOT DONE
Allow consultants and MSPs to manage multiple client workspaces from a single console. Support white-labeling, client-specific branding, and aggregated reporting across clients. Track service delivery metrics (questionnaires completed, gaps remediated, Trust Center articles published) per client. This creates a channel sales motion where consultants adopt Trust Copilot as their delivery platform.

### E7-39: Build cross-party evidence sharing — NOT DONE
Allow controlled evidence sharing across workspaces: a seller can share specific evidence items or Trust Center articles with a buyer's workspace, an auditor can share validation notes back to the seller, and a consultant can share templates across clients. Maintain full audit trails of what was shared, when, and with whom. Revocation should be instant and verifiable.

### E7-40: Build trust supply chain view — NOT DONE
For organizations that are both buyers and sellers (e.g., they have vendors and they respond to their own customers' questionnaires), show the full trust supply chain: upstream vendor compliance posture, internal controls, and downstream customer commitments. Surface risks that cascade: "Your cloud vendor's SOC 2 expired. This affects 3 controls and 12 questionnaire answers across 4 customer deals."

---

## Epic 8 — Predictive Trust (know what buyers will ask before they ask)

### E8-41: Build questionnaire pattern analysis — NOT DONE
Analyze all questionnaires processed across the platform (anonymized) to identify patterns: which questions appear most frequently by industry, buyer size, framework, and region. Build a frequency model that predicts which questions are most likely to appear in a new questionnaire based on buyer characteristics. This turns historical data into a predictive asset.

### E8-42: Build the preflight pack generator — NOT DONE
For a given target buyer segment (e.g., fintech, 1000+ employees, SOC 2 + HIPAA), auto-generate a "preflight pack" listing: the 50 most likely questions, which answers are ready, which have low confidence, which evidence is stale, and which gaps need filling before outreach. Sales teams should be able to run a preflight before engaging a prospect, compressing diligence preparation from reactive to proactive.

### E8-43: Build "likely blockers" prediction — NOT DONE
Based on questionnaire history and buyer patterns, predict the specific topics most likely to cause deal friction: logging retention, incident response testing, privileged access review, subprocessor lists, data residency. Display these as a ranked list per deal or prospect with action items: "Approve these 3 answers and upload updated penetration test results before your next call." This is trust as a GTM function.

### E8-44: Build proactive evidence refresh recommendations — NOT DONE
Analyze evidence freshness, upcoming deal timelines, and predicted questionnaire topics to recommend which evidence to refresh and when. Example: "Your penetration test report expires in 14 days. Three deals with Q2 close dates will need it. Schedule a refresh now." This prevents last-minute scrambles that delay deals and erode buyer confidence.

### E8-45: Build segment-level trust readiness scoring — NOT DONE
For each target segment the company sells into, compute an overall trust readiness score: "You are 92% ready for enterprise fintech buyers, 78% ready for mid-market healthtech, 61% ready for government." Show which investments (evidence uploads, control fixes, answer approvals) would move each segment's score the most. This gives leadership a strategic view of where trust investments should go.

---

## Epic 9 — Benchmark Network Effect (aggregated intelligence moat)

### E9-46: Build anonymized questionnaire analytics — NOT DONE
Aggregate question frequency, topic distribution, framework distribution, and questionnaire length across all workspaces (fully anonymized, opt-in). Compute benchmarks: "The average SOC 2 questionnaire has 187 questions. Yours had 243 — 30% above average." This gives individual customers context they cannot get on their own and creates a data asset that grows with the platform.

### E9-47: Build evidence strength benchmarking — NOT DONE
Compare a workspace's evidence coverage, freshness, and approval rates against anonymized platform averages for their industry and size. Show where they're ahead ("Your access control evidence is stronger than 85% of similar companies") and where they're behind ("Your incident response evidence is in the bottom quartile"). This creates urgency and direction without prescribing specific actions.

### E9-48: Build answer quality benchmarking — NOT DONE
Compare a workspace's answer acceptance rate, edit frequency, and follow-up rate against platform averages. Show which topic areas produce the best and worst outcomes relative to peers. "Teams your size typically achieve 93% acceptance on access control questions — you're at 81%. Here are the top-performing answer patterns." This turns the memory system into a coaching tool.

### E9-49: Build review time benchmarking — NOT DONE
Track and benchmark questionnaire turnaround time, review duration, and approval velocity across the platform. Show teams how they compare: "Your average questionnaire completion time is 4.2 hours. The platform median for your segment is 2.1 hours." Identify bottlenecks: "Your data privacy answers take 3x longer to review than average — consider investing in stronger evidence for this category."

### E9-50: Build "what teams like you do" recommendations — NOT DONE
Based on aggregated patterns, recommend specific actions: "Companies in your segment typically upload these 5 document types first," "Teams that add GitHub integration reduce access control review time by 40%," "Workspaces that approve answers within 24 hours close deals 2.3x faster." These recommendations become more valuable as the platform grows, creating a network effect that individual competitors cannot replicate.

---

## Epic 10 — Live Proof Brand (make trust a continuous, visible signal)

### E10-51: Build the live trust status page — NOT DONE
Create a public-facing page per workspace that shows real-time compliance posture: controls passing, evidence freshness, last connector sync, active certifications, and overall trust score. Think of it as a "status page for trust." Buyers can bookmark it and check back anytime. Unlike a static Trust Center, this page updates automatically based on connector signals and control evaluations.

### E10-52: Build live evidence badges — NOT DONE
Generate embeddable badges (like GitHub build status badges) that show real-time compliance status: "SOC 2 controls: 47/48 passing," "Evidence freshness: 98%," "Trust score: A." Companies can embed these on their website, sales decks, and email signatures. The badges link back to the Trust Center for details. This turns compliance posture from a hidden document into a visible, always-current signal.

### E10-53: Build live proof in questionnaire answers — NOT DONE
When generating questionnaire answers, include a "live proof" indicator showing: when the underlying evidence was last verified, whether it came from a live connector or a static upload, and the current control status. Export this metadata in the delivered questionnaire. "This answer is backed by a live AWS connector, last synced 2 hours ago, with all related controls passing." This is fundamentally stronger than a citation to a PDF uploaded 6 months ago.

### E10-54: Build trust change notifications for buyers — NOT DONE
Allow buyers who have received questionnaire answers or deal room access to subscribe to change notifications. When a control flips, evidence is updated, or an answer changes, notify the buyer automatically. This turns the trust relationship from a point-in-time exchange into an ongoing channel. Buyers no longer need to re-request questionnaires to check if anything changed.

### E10-55: Build the trust timeline — NOT DONE
Create a chronological view of all trust-relevant events across a workspace: evidence uploaded, controls evaluated, answers approved, questionnaires completed, deals unblocked, remediations executed, promises made, promises verified. This is the single narrative of a company's trust posture over time. It's valuable for audits, board reporting, and demonstrating continuous compliance to any stakeholder.

---

## Epic Summary

| Epic | Tickets | Status |
|------|---------|--------|
| 1. Deal-Aware Trust | E1-01 through E1-07 | ALL NOT DONE |
| 2. Promise Engine | E2-08 through E2-13 | ALL NOT DONE |
| 3. Remediation Engine | E3-14 through E3-19 | ALL NOT DONE |
| 4. Buyer Experience | E4-20 through E4-24 | ALL NOT DONE |
| 5. Proof Graph | E5-25 through E5-30 | ALL NOT DONE |
| 6. Outcome-Learning Memory | E6-31 through E6-35 | ALL NOT DONE |
| 7. Multi-Party Trust Ops | E7-36 through E7-40 | ALL NOT DONE |
| 8. Predictive Trust | E8-41 through E8-45 | ALL NOT DONE |
| 9. Benchmark Network | E9-46 through E9-50 | ALL NOT DONE |
| 10. Live Proof Brand | E10-51 through E10-55 | ALL NOT DONE |
| **Total** | **55 tickets** | **55 NOT DONE** |

> Don't spend the next cycle just adding more connectors. The above-and-beyond move is to build, in this order, a deal layer, a promise layer, a remediation layer, and a buyer layer on top of the evidence graph you already have. That sequence preserves the fast deal-unblocking motion while creating a product that is much harder to commoditize.
