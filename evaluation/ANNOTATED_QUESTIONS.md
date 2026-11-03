# Marine Evidence Finder — Grounded Evaluation Benchmark v1

**Corpus:** 8 uploaded scientific PDFs. **Questions:** 20 (10 fact, 5 synthesis, 5 unsupported).

**Page numbers:** PDF viewer page indices (1-based), not journal pagination. Each short evidence quotation was verified against the text extracted from that exact uploaded PDF page.

## Evaluation questions and gold answers

### Q01: How did bottlenose dolphin whistle frequencies and contour complexity change under increased ambient noise in Fouda et al. (2018)?

*Type:* fact · *Split:* dev · *Difficulty:* easy

**Gold answer:** Fouda et al. observed higher whistle frequencies and reduced contour complexity at elevated ambient noise levels, mainly associated with shipping. This is an observed acoustic response; the study did not directly measure whether communication success declined.

**Required facts:**
- Whistle frequencies rose under elevated ambient noise.
- Whistle contour complexity declined.
- Communication impairment was a possibility, not a directly measured outcome.

**Evidence:**
- **P01 · PDF page 1** (support): “Increases in ship noise, both within and below the dolphins’ call bandwidth, resulted in higher dolphin whistle frequencies and a reduction in whistle contour complexity, an acoustic feature associated with individual identification. Consequently, the”
- **P01 · PDF page 3** (limitation): “It is unknown what impact this shortening and simplification of calls may have on the information communicated. There are”

**Do not claim:** Noise simplification was proven to kill calves or reduce population growth.

### Q02: Compare Fouda et al. (2018) and Marley et al. (2017): what acoustic and other behavioural responses were reported, and why should they not be treated as identical causal experiments?

*Type:* synthesis · *Split:* test · *Difficulty:* hard

**Gold answer:** Fouda detected higher-frequency, less-complex bottlenose dolphin whistles during noisier conditions. Marley found whistle variation and changes in movement and activity budgets in a busy estuary: notably more travel, less rest/socialising, and faster swimming only in some activity states. The observational contexts, species populations and explanatory factors differ; vessel presence and other context cannot simply be attributed entirely to sound.

**Required facts:**
- Fouda reports elevated frequency and simplified contours.
- Marley reports acoustic changes alongside movement and activity-budget shifts.
- The studies are observational and do not establish a universal single-cause mechanism.

**Evidence:**
- **P01 · PDF page 1** (support): “Increases in ship noise, both within and below the dolphins’ call bandwidth, resulted in higher dolphin whistle frequencies and a reduction in whistle contour complexity, an acoustic feature associated with individual identification. Consequently, the”
- **P02 · PDF page 1** (support): “Dolphins significantly increased their average movement speeds in high vessel densities, but only for some activity states. Behavioural budgets also changed in the presence of vessels, with animals spending greater time travelling and less time resting or socialising. Finally”
- **P02 · PDF page 2** (limitation): “In practice, it can be difficult to disentangle the effects of physical boat presence and associated noise28,46, with results also being confounded by the fact”

**Do not claim:** Both papers ran the same randomised intervention.; All swimming states accelerated at high vessel density.

### Q03: How many dolphin calves died specifically because ship noise simplified their mothers’ whistles in these eight studies?

*Type:* abstention · *Split:* test · *Difficulty:* medium

**Gold answer:** This death count cannot be determined from the eight papers. The whistle study measured acoustic characteristics, not calf mortality or a causal mortality pathway. No numerical answer should be supplied.

**Required facts:**
- Explicitly say the causal death count is not established by this corpus.
- Distinguish possible communication consequences from measured mortality.

**Evidence:**
- **P01 · PDF page 3** (limitation): “There are, to our knowledge, currently no studies that have addressed the call receivers to determine if and how call simplification may affect dolphin fitness. Vocal”

**Do not claim:** Invent any calf mortality number.; Say the paper measured deaths caused by whistle changes.

### Q04: In Dunlop (2019), what were the modelled communication ranges for low-frequency humpback social vocalizations in typical wind noise and around 105 dB re 1 µPa vessel-dominated noise?

*Type:* fact · *Split:* dev · *Difficulty:* easy

**Gold answer:** The modelled low-frequency communication range was about 4 km under typical wind-dominated conditions and about 2 km under mean vessel-dominated noise of 105 dB re 1 µPa; it was approximately halved. These are acoustic-model estimates, not direct measurements of the animals’ audiograms.

**Required facts:**
- Wind-dominated baseline approximately 4 km.
- At ~105 dB re 1 µPa vessel noise approximately 2 km.
- These are modelled acoustic communication distances.

**Evidence:**
- **P03 · PDF page 1** (support): “In typical wind noise, a signaller’s communication space was estimated to extend to 4 km, which agreed with the maximum separation distance between groups that socially interacted. An”
- **P03 · PDF page 10** (support): “In average vessel-dominated noise (105 dB re 1 μPa), the modelled communication space of humpback whale low-frequency vocalizations reduced by half to 2 km. These results are similar to modelled loss in communication”

**Do not claim:** Directly measured hearing range for every whale.; A universal upper vessel-noise threshold.

### Q05: Why did Dunlop (2019) conclude that acoustic masking alone did not fully explain reduced humpback group interactions?

*Type:* synthesis · *Split:* test · *Difficulty:* hard

**Gold answer:** The model predicted a smaller acoustic communication network in ship noise, but observed interactions dropped more than could be explained using realistic receiver distributions and masking assumptions. At close distances signals could remain audible; a physical vessel-presence effect was suggested as an additional influence, not proven as the unique cause.

**Required facts:**
- Modelled acoustic communication space was reduced.
- Observed interactions were not fully accounted for by masking alone.
- Vessel presence is proposed as an additional explanation, with remaining uncertainty.

**Evidence:**
- **P03 · PDF page 10** (support): “Observed social interactions in vessel-dominated noise, however, found a 50% reduction in the likelihood of a signalling group interacting with a receiver group within the 2 km interaction zone. Therefore, using the random”
- **P03 · PDF page 10** (limitation): “This discrepancy, as explained later, is likely to be due to the physical presence of the vessel. Though this study focused on the acoustic environment and behaviour”
- **P03 · PDF page 8** (support): “Even in vessel-dominated noise, many received signals would have been above noise at this close-by separation distance (figure 1), suggesting masking was not a significant issue. If using 105”

**Do not claim:** Masking alone fully explains all behaviour.; The physical-presence mechanism was proven uniquely.

### Q06: What is the exact universal vessel-noise threshold above which every humpback whale becomes completely unable to communicate?

*Type:* abstention · *Split:* dev · *Difficulty:* medium

**Gold answer:** No such universal threshold can be derived from Dunlop (2019) or the other included studies. Communication range varies with signal frequency, background sound, propagation, behavioural context and assumptions about hearing; Dunlop’s ranges are model-based rather than a universal complete-silence cutoff.

**Required facts:**
- Refuse to provide an exact universal dB threshold.
- Explain dependence on acoustic context and model assumptions.

**Evidence:**
- **P03 · PDF page 1** (limitation): “Since no empirical data exist on baleen whale hearing, the consequences of this are usually assumed, being the modelled reduction in their communication space. Here, the communication space”
- **P03 · PDF page 8** (scope): “By received noise levels of 110 dB re 1 μPa, which is considered to be high wind noise, or noise from a close-by (within 2 km) vessel, the modelled communication”

**Do not claim:** Turn 105 or 110 dB re 1 µPa into a universal cutoff.

### Q07: In Blair et al. (2016), what changes in foraging were associated with increased ship noise for tagged humpback whales?

*Type:* fact · *Split:* dev · *Difficulty:* easy

**Gold answer:** In 10 tagged, bottom-foraging humpback whales, increasing ship noise was associated with slower descent rates and fewer side-roll feeding events per dive. Five of 18 ship passages included no-side-roll dives. The study assessed within-dive behaviour, not population survival.

**Required facts:**
- 10 tagged foraging whales.
- Slower descent rate.
- Fewer side-roll feeding events per dive.
- Five of eighteen ship passages included no-roll dives.

**Evidence:**
- **P04 · PDF page 1** (support): “Data were collected from 10 fora- ging whales using non-invasive archival tags that simultaneously recorded underwater movements and the acoustic environment at the whale. Using mixed models, we assess”
- **P04 · PDF page 1** (support): “We found significant effects on foraging, including slower descent rates and fewer side-roll feeding events per dive with increasing ship noise. During 5 of 18 ship passages, dives without side-rolls were observed. These”

**Do not claim:** Measured whale population decline or reproductive success.

### Q08: Compare ship-noise-associated foraging disruptions in humpback whales (Blair et al.) and harbour porpoises (Wisniewska et al.). Can one common exposure threshold be inferred?

*Type:* synthesis · *Split:* test · *Difficulty:* hard

**Gold answer:** Blair reported slower descent and fewer side-roll feeding events in humpbacks. Wisniewska observed foraging interruptions and fewer prey-capture attempts in harbour porpoises, notably above 96 dB re 1 µPa in the 16-kHz third-octave band in that study. Both suggest behavioural disruption, but the noise metrics, species and experimental context differ; the porpoise value is not a universal threshold for all cetaceans.

**Required facts:**
- Humpbacks: fewer side-roll feeding events and slower descent.
- Porpoises: disrupted foraging and fewer prey-capture attempts at high received noise.
- 96 dB refers to the reported 16-kHz one-third-octave measure, not a cross-species universal threshold.

**Evidence:**
- **P04 · PDF page 1** (support): “We found significant effects on foraging, including slower descent rates and fewer side-roll feeding events per dive with increasing ship noise. During 5 of 18 ship passages, dives without side-rolls were observed. These”
- **P05 · PDF page 1** (support): “Tagged porpoises encountered vessel noise 17–89% of the time and occasional high-noise levels coincided with vigorous fluking, bottom diving, interrupted foraging and even cessation of echolocation, leading to significantly fewer prey capture attempts at received levels greater than 96 dB re 1 mPa (16”

**Do not claim:** 96 dB is the universal marine-mammal behavioural threshold.; Direct proof that either population is shrinking.

### Q09: By what exact percentage did vessel-noise-related foraging disruption reduce lifetime reproductive success in both humpback whales and harbour porpoises?

*Type:* abstention · *Split:* dev · *Difficulty:* medium

**Gold answer:** Neither cited foraging study quantifies a lifetime reproductive-success percentage for both species. They report short-term/within-dive behavioural changes and discuss possible long-term consequences. No numeric percentage can be inferred.

**Required facts:**
- Say the exact lifetime reproductive-success percentages are not reported in the corpus.
- Distinguish short-term behavioural endpoints from potential long-term fitness effects.

**Evidence:**
- **P04 · PDF page 1** (limitation): “This measureable reduction in within-dive foraging effort of individual whales could potentially lead to population-level impacts of shipping noise on baleen whale foraging success. 1. Introduction Increased levels of”
- **P05 · PDF page 1** (limitation): “If such exposures occur frequently, porpoises, which have high metabolic requirements, may be unable to compensate energetically with negative long-term fitness consequences. That shipping noise disrupts foraging in the high-frequency-hearing porpoise”

**Do not claim:** Invent a percentage.; Present a hypothetical fitness effect as measured.

### Q10: Following the September 2001 shipping reduction in the Bay of Fundy, what acoustic and physiological changes did Rolland et al. (2012) report?

*Type:* fact · *Split:* dev · *Difficulty:* medium

**Gold answer:** The researchers found roughly a 6 dB reduction in overall underwater noise and a significant decline in noise below 150 Hz, accompanied by lower baseline faecal glucocorticoid metabolite levels in North Atlantic right whales. The comparison was a retrospective natural experiment, not a randomised causal trial.

**Required facts:**
- Approximately 6 dB decline in underwater noise.
- Significant decline below 150 Hz.
- Lower faecal glucocorticoid metabolites.
- Retrospective non-repeatable natural experiment.

**Evidence:**
- **P06 · PDF page 1** (support): “Here, we show that reduced ship traffic in the Bay of Fundy, Canada, following the events of 11 September 2001, resulted in a 6 dB decrease in underwater noise with a significant reduction below 150 Hz. This noise reduction was associated with decreased baseline levels of stress-related”
- **P06 · PDF page 4** (limitation): “this is a retrospective analysis based on a non-repeatable event, with all of the inherent limitations. Because the study was unplanned, there are no compar- able acoustic recordings from the Bay of”

**Do not claim:** Stress-hormone decline proves ship noise caused every stress response.

### Q11: How do Rolland et al. (2012) and Dunlop (2019) differ in the outcomes they assessed and in the strength of causal conclusions?

*Type:* synthesis · *Split:* test · *Difficulty:* hard

**Gold answer:** Rolland compared underwater noise and faecal stress-hormone metabolites in right whales after a real but unplanned change in traffic; it supports an association and has retrospective limitations. Dunlop used acoustic communication-space modelling combined with observations of humpback whale group interactions. The endpoints, species and study designs differ, and neither directly establishes population-level survival consequences.

**Required facts:**
- Rolland measured acoustic and physiological correlates in right whales.
- Dunlop modelled acoustic space and analysed observed humpback social interaction.
- Different endpoints and limits on strong causal or population-level claims.

**Evidence:**
- **P06 · PDF page 1** (support): “This noise reduction was associated with decreased baseline levels of stress-related faecal hormone metabolites (glucocorticoids) in North Atlantic right whales (Eubalaena glacialis). This is the first evidence that exposure to low-frequency ship noise”
- **P06 · PDF page 4** (limitation): “this is a retrospective analysis based on a non-repeatable event, with all of the inherent limitations. Because the study was unplanned, there are no compar- able acoustic recordings from the Bay”
- **P03 · PDF page 1** (support): “Behavioural data on their social interactions were then used to inform these models. In typical wind noise, a signaller’s communication space was estimated to extend to 4”

**Do not claim:** The studies both conducted randomised noise treatments.; Both directly measured whale survival effects.

### Q12: How many North Atlantic right whales died between 2001 and 2010 specifically because ship-noise-induced chronic stress caused fatal illness?

*Type:* abstention · *Split:* dev · *Difficulty:* medium

**Gold answer:** The supplied papers do not provide a causal death count for this proposed chain. Rolland et al. examined ship-noise exposure and stress-related faecal biomarkers around 2001, with limitations on causal attribution. No numerical answer is supported.

**Required facts:**
- Explicitly decline the attributable death count.
- State that physiological associations do not directly measure fatal illness caused by chronic noise.

**Evidence:**
- **P06 · PDF page 1** (scope): “This noise reduction was associated with decreased baseline levels of stress-related faecal hormone metabolites (glucocorticoids) in North Atlantic right whales (Eubalaena glacialis). This is the first evidence that exposure”
- **P06 · PDF page 4** (limitation): “this is a retrospective analysis based on a non-repeatable event, with all of the inherent limitations. Because the study was unplanned, there are no compar- able acoustic recordings from the Bay”

**Do not claim:** Invent a death count.; Claim that the study tracked ten-year noise-caused fatalities.

### Q13: In ZoBell et al. (2021), what mean differences between rewarded and control transits were reported for vessel speed, broadband source level and sound exposure level?

*Type:* fact · *Split:* dev · *Difficulty:* easy

**Gold answer:** In the 2014–2017 transit-by-transit comparison, rewarded transits were 4.8 knots (2.5 m/s) slower on average; their broadband source level was 5.2 dB lower, and their sound exposure level was 4.7 dB lower. These were measured/estimated acoustic contrasts between vessel groups, not a direct population-benefit estimate.

**Required facts:**
- 4.8 knots or 2.5 m/s slower.
- 5.2 dB lower broadband source level.
- 4.7 dB lower sound exposure level.

**Evidence:**
- **P07 · PDF page 5** (support): “The average reduction in SOG, SL, and SEL between control and rewarded groups was 2.5 m s−1 (4.8 knots), 5.2 dB, and 4.7 dB, respectively. While the fleet-based VSR program was active, broadband SL”
- **P07 · PDF page 2** (method): “In this study, we evaluated the efficacy of a VSR program in the SBC for reducing underwater radiated noise of participating vessels. By using long-term acoustic records from the SBC, we”

**Do not claim:** A measured increase in whale survival of 4.7%.; A randomised trial of whale health.

### Q14: Compare how ZoBell et al. (2021) and Findlay et al. (2023) evaluate vessel-speed reduction: what is measured or estimated in the field versus simulated?

*Type:* synthesis · *Split:* test · *Difficulty:* hard

**Gold answer:** ZoBell analysed tracked transits and acoustic records from an incentive programme, comparing source-level and exposure-level estimates for participating and other vessels. Findlay used a vessel-exposure simulation model to estimate how slower vessels change noise footprints and exposure proxies for marine mammals. Both support acoustic mitigation, but neither measured how many whales survived because of it.

**Required facts:**
- ZoBell: field AIS and acoustic data used to estimate ship acoustic levels.
- Findlay: simulation of noise footprints/exposure impact proxies.
- Neither directly estimated extra whale lives saved.

**Evidence:**
- **P07 · PDF page 2** (support): “In this study, we evaluated the efficacy of a VSR program in the SBC for reducing underwater radiated noise of participating vessels. By using long-term acoustic records from the SBC, we compared ship source levels”
- **P08 · PDF page 1** (support): “We use a vessel exposure simulation model to examine how reducing vessel source levels through slowdowns and technological modifications can lessen impacts on marine mammals. We show that the area exposed to ship noise reduces markedly”
- **P08 · PDF page 4** (support): “To assess the effectiveness of the slowdown approach at reducing noise impacts to marine mammals, we modeled three speed scenar- ios (high speed and a 20 and 50% slowdown), assuming that vessels were passing a stationary animal at either 300-”

**Do not claim:** Findlay directly followed whale survival after reducing every vessel speed.; ZoBell demonstrated a precise population recovery rate.

### Q15: Exactly how many additional whales survived through 2025 because of the Santa Barbara Channel vessel-speed reduction programme?

*Type:* abstention · *Split:* test · *Difficulty:* medium

**Gold answer:** No attributable additional-whale-survival count through 2025 is provided by these papers. ZoBell reports vessel acoustic outcomes, while Findlay models noise exposure; neither supplies this longitudinal counterfactual survival estimate.

**Required facts:**
- State that a 2025 attributable survival count is unavailable in this eight-paper corpus.
- Explain why acoustic mitigation results cannot yield that count alone.

**Evidence:**
- **P07 · PDF page 1** (scope): “This study quantified the reduction in source levels (SLs) and sound exposure levels (SELs) for ships participating in two variations of a vessel speed reduction (VSR) program. SLs and SELs of individual”
- **P08 · PDF page 1** (scope): “We use a vessel exposure simulation model to examine how reducing vessel source levels through slowdowns and technological modifications can lessen impacts on marine mammals. We show that the area exposed to ship”

**Do not claim:** Invent a count of saved whales.; Treat reduced sound-level dB as saved individual whales.

### Q16: How many high-quality whistles and separate encounters were analysed by Fouda et al. (2018)?

*Type:* fact · *Split:* test · *Difficulty:* easy

**Gold answer:** The analysis included 200 high-quality whistles from 16 encounters.

**Required facts:**
- 200 high-quality whistles.
- 16 encounters.

**Evidence:**
- **P01 · PDF page 2** (support): “In total, 200 high-quality whistles from 16 encounters were used in the analysis (figure 1, [16]). Whistles occurred in”

**Do not claim:** Confuse number of whistles with number of dolphins.

### Q17: In Marley et al. (2017), which dolphin activity states showed significantly higher average speeds at high vessel densities, and which did not?

*Type:* fact · *Split:* dev · *Difficulty:* medium

**Gold answer:** Resting and socialising showed significantly increased average movement speed with higher vessel densities. Average speeds for travelling, foraging and milling did not differ significantly between vessel-density contexts. The authors caution that sample sizes were small for high-density resting/socialising observations.

**Required facts:**
- Resting and socialising speeds increased.
- No significant difference for travelling, foraging and milling.
- Small high-density subsamples warrant caution.

**Evidence:**
- **P02 · PDF page 2** (support): “Mann-Whitney U Tests showed no significant differences (p > 0.05) in average speed between vessel contexts for travelling, forag- ing or milling. Both resting and socialising average speeds significantly increased with increasing vessel densities (respectively, U = 176.5, p”
- **P02 · PDF page 2** (support): “Both resting and socialising average speeds significantly increased with increasing vessel densities (respectively, U = 176.5, p = 0.01673; U = 503, p = 0.04216; Fig. 2a). However, these results should be interpreted with caution given the low sample sizes associated with”

**Do not claim:** All activity states significantly accelerated.

### Q18: How many harbour porpoises were tagged by Wisniewska et al. (2018), what fraction of their time contained vessel noise, and at what specified acoustic measurement were prey-capture attempts significantly fewer?

*Type:* fact · *Split:* test · *Difficulty:* medium

**Gold answer:** Seven harbour porpoises carried acoustic tags. Vessel noise was detected 17–89% of the time across tagged animals. Significantly fewer prey-capture attempts were reported for received levels greater than 96 dB re 1 µPa measured in the 16-kHz third-octave band; this is study-/measurement-specific, not a universal cetacean threshold.

**Required facts:**
- 7 tagged porpoises.
- Vessel noise present 17–89% of the time.
- Fewer attempts above 96 dB re 1 µPa in a 16-kHz third-octave band.

**Evidence:**
- **P05 · PDF page 1** (support): “Here, we used animal-borne acoustic tags to measure vessel noise exposure and foraging efforts in seven harbour porpoises in highly trafficked coastal waters. Tagged porpoises encountered vessel noise 17–89% of the time and occasional high-noise”
- **P05 · PDF page 1** (support): “Tagged porpoises encountered vessel noise 17–89% of the time and occasional high-noise levels coincided with vigorous fluking, bottom diving, interrupted foraging and even cessation of echolocation, leading to significantly fewer prey capture attempts at received levels greater than 96 dB re 1 mPa (16 kHz”

**Do not claim:** 96 dB is a broadband threshold for all marine mammals.

### Q19: According to ZoBell et al. (2021), what participation condition was associated with significant acoustic reductions in the 2018 fleet-based speed-reduction programme?

*Type:* fact · *Split:* dev · *Difficulty:* medium

**Gold answer:** The fleet-based results found statistically significant source-level and sound-exposure-level reductions when a fleet cooperated by slowing at least 25% of its transits. The paper also identifies 10 knots or less as an effective slowing target; the 25% figure refers to programme cooperation, not a 25% speed reduction.

**Required facts:**
- Participation/cooperation in speed reductions for at least 25% of transits.
- Significant differences in source and exposure levels.
- Do not confuse the participation rate with the size of a speed reduction.

**Evidence:**
- **P07 · PDF page 1** (support): “In the 2018 fleet-based program, there were statistical differences between the SLs and SELs of fleets that participated with varying degrees of cooperation. Significant reductions in SL and SEL relied on cooperation of 25% or more in slowing vessel speed. This analysis highlights”

**Do not claim:** Each ship had to reduce speed by exactly 25%.

### Q20: In Findlay et al. (2023), by how many dB was mean cargo-vessel source level predicted to change for a 20% speed reduction?

*Type:* fact · *Split:* dev · *Difficulty:* easy

**Gold answer:** The modelling predicted an approximately 6 dB reduction in mean vessel source level for a 20% slowdown; the study also estimated around an 18 dB reduction for a 50% slowdown. These values are model predictions, not direct measurements of improved whale survival.

**Required facts:**
- 20% speed reduction -> predicted 6 dB lower mean source level.
- Specify that the value is modelled/predicted.

**Evidence:**
- **P08 · PDF page 3** (support): “Specifically, a 20% reduction in speed decreases the predict- ed mean source level by 6 dB and a 50% speed reduction drops mean source levels by 18 dB (Fig. 3A). This level reduction is approxi- mately”
- **P08 · PDF page 1** (method): “We use a vessel exposure simulation model to examine how reducing vessel source levels through slowdowns and technological modifications can lessen impacts on marine mammals. We show that the area exposed”

**Do not claim:** 6 dB fewer whales affected.; Directly observed changes to whale survival.

