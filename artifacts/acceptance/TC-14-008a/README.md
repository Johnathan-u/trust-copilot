# TC-14-008a initial diagnostic evidence

Actual PR #133 artifacts: axe `12956632966`, report `12957057238`. The downloaded
`axe-actions-light-360.json` reports a serious color-contrast violation with two
affected nodes. `observed-failure.json` preserves that summary exactly; it is
historical evidence, not a fresh acceptance scan.

The coordinator's artifact review observed the theme switch roughly 83 ms before
the axe partial run, within a 150 ms color transition. This is insufficient to
identify the actual failing nodes or establish causation. The initial change is
five added lines in `microcopy-states.spec.ts`: retain full violation objects and
attach the JSON before either original assertion can fail.

The original summaries and all six theme/viewport scan combinations remain.
Existing CI artifact upload and count/schema checks accept the additional field.
No metadata is discarded, no assertion is changed, and no scan is delayed.

Local verification confirms all 58 assertion expressions retain identical source
and ASTs. The scan, summary mapping, blocking filter, report metadata and all
other source bytes are unchanged. Synthetic serious, moderate and zero-violation
inputs exercise the actual extracted helper with real Playwright assertions:
the attachment precedes the applicable failure, and target/HTML/color/check data
survive serialization. The axe result and attachment sink are test doubles;
this is diagnostic control-path evidence, not a browser or contrast result.

The locked browser is absent. No browser installation, dependency change,
alternate renderer or product/style workaround was attempted. Independent review
and actual CI diagnostics remain pending; the cause of the contrast failure is
unresolved.
