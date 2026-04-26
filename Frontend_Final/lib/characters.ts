export type CharacterId = 'rachael' | 'eric' | 'faith'

export interface Character {
  id: CharacterId
  initial: string
  name: string
  role: string
  moodPill: string
  maxMessages: number
  headerBg: string
  bubbleBg: string
  bubbleBorder: string
  textColor: string
  avatarBg: string
  avatarText: string
  nameColor: string
  signoffMessage: string
  prompts: string[]
  responses: string[][]
  signoff: string
}

export const CHARACTERS: Character[] = [
  {
    id: 'rachael',
    initial: 'R',
    name: 'Rachael',
    role: 'Scientific Rigour',
    moodPill: 'Sceptical mode',
    maxMessages: 5,
    headerBg: '#fff8f6',
    bubbleBg: '#fff8f6',
    bubbleBorder: '#f5c4b3',
    textColor: '#2a1008',
    avatarBg: '#FAECE7',
    avatarText: '#993C1D',
    nameColor: '#993C1D',
    signoffMessage: "Right. I've interrogated this enough. The hypothesis has bones — fragile ones, but bones. Eric will sort the practicalities. Don't embarrass us.",
    prompts: [
      'What is your hypothesis?',
      'Justify your controls',
      'What could falsify this?',
      'Have you checked prior literature?',
      'What is your sample size rationale?',
    ],
    responses: [
      [
        "A hypothesis, is it? How charmingly optimistic. Walk me through the mechanism — and I mean the actual mechanism, not a hand-wave.",
        "I've seen a hundred proposals like this crumble in peer review. What makes yours different? Be specific.",
        "Interesting. Now explain why your independent variable is actually independent. Because from where I'm standing, it looks entangled with three confounders.",
      ],
      [
        "Controls. You mentioned controls. Name them. All of them. And explain why each one is necessary rather than merely decorative.",
        "A negative control is not optional. A positive control is not optional. What exactly are you controlling for, and how?",
        "I'll need you to justify every single control group. Reviewers will ask, and 'it seemed sensible' is not an answer.",
      ],
      [
        "Now we're getting somewhere. What would it take to falsify your hypothesis? If you can't answer that, you don't have science — you have a belief system.",
        "Give me three concrete observations that would prove you wrong. Not vague ones. Specific, measurable, falsifying evidence.",
        "Karl Popper is watching you. What's your falsifiability criterion? If your experiment can't fail, it can't succeed either.",
      ],
      [
        "Literature. Tell me you've done a systematic review and not just a quick Google Scholar search at midnight.",
        "Who has published in this space? What gaps does your work fill? 'Nobody has done this exactly' is not sufficient novelty.",
        "Cite three papers that directly inform your methodology. I want authors, years, and one sentence on why each is relevant.",
      ],
      [
        "Sample size. The graveyard of underpowered studies is full of researchers who thought n=10 was enough. What's your power analysis?",
        "What effect size are you expecting, and what's your basis for that estimate? I need numbers, not intuitions.",
        "Justify your n. Show me the power calculation. If you haven't done one, do it before you speak to me again.",
      ],
    ],
    signoff: "Right. I've interrogated this enough. The hypothesis has bones — fragile ones, but bones. Eric will sort the practicalities. Don't embarrass us.",
  },
  {
    id: 'eric',
    initial: 'E',
    name: 'Eric',
    role: 'Lab Logistics',
    moodPill: 'Budget mode',
    maxMessages: 5,
    headerBg: '#f6f8ff',
    bubbleBg: '#f6f8ff',
    bubbleBorder: '#B5D4F4',
    textColor: '#08101a',
    avatarBg: '#E6F1FB',
    avatarText: '#185FA5',
    nameColor: '#185FA5',
    signoffMessage: "Alright. I've mapped the resources, flagged the risks, and allocated the budget. Faith has the final say on the vision side. Over to her.",
    prompts: [
      'Looks correct to me',
      'We also need a flow cytometer',
      'Missing: sterile dissection tools',
      'The micropipette set is on order',
      'Add CO\u2082 sensor to the list',
    ],
    responses: [
      [
        "Right. I've just checked the inventory against what you've described. Here is the confirmed equipment list: centrifuge (we have it), plate reader (booked through Thursday — needs scheduling), gel electrophoresis rig (available), -80°C freezer space (limited — flag this). We are missing a calibrated micropipette set in the 1–10 µL range. Ours failed QC last week. I'll raise a purchase order today.",
        "I ran a check on the lab manifest. Equipment you'll need: benchtop spectrophotometer (in), thermal cycler (in, but due for maintenance), biosafety cabinet (booked Mon–Wed, we have a window Thurs afternoon). We are missing sterile dissection tools — the last set hasn't come back from sterilisation. I've flagged it but don't count on it before next week.",
        "Checked the stores. Core equipment accounted for: incubator shakers (two free units), analytical balance (calibrated, good), vacuum filtration setup (available). We are missing a CO₂ sensor for environmental monitoring during incubation — that's a gap. Either we borrow from Building C or I source one through the shared equipment pool. I'll make some calls.",
      ],
      [
        "Budget check done. Here is where we stand: reagents (ELISA kit, buffers, standards) — approximately £320 per run. Consumables (tips, tubes, plates) — £85. Instrument time on the plate reader — £40/hour, estimate 6 hours. Total per-run estimate: ~£620. We are missing line-item costs for waste disposal and PPE restocking — those are never zero and reviewers always notice. I'll add £80 contingency.",
        "I've costed this out. Reagent spend: ~£450 if you're using the commercial kit, ~£210 if we make up the buffers in-house. I'd recommend in-house — we have the components. Consumables: £70. Equipment hire (external flow cytometer): £180/session, two sessions minimum. Running total: ~£460–730. We are missing a quote for courier costs if samples need to go offsite. That's a budget gap I'd fix before submission.",
        "Quick cost breakdown: primary antibodies — £280 (we have two in stock, need one more), secondary antibodies — £95 (need to order), blocking solution — £18 (in stock), film/imaging — £60/run. We are missing a line for disposal of biological waste — that fee went up in Q1 and nobody updated the template. I'll get you the correct figure from facilities.",
      ],
      [
        "I've cross-checked the safety documentation. COSHH assessment exists for the buffer chemicals — good. Risk register is up to date for the centrifuge. We are missing a COSHH form for the new fixative reagent you mentioned. That one is classed as a Category 3 irritant and needs a separate assessment before it enters the lab. I'll draft it — I need the exact product name and CAS number from you.",
        "Safety audit done. PPE requirements covered for most steps. Sharps disposal protocol — confirmed. Biohazard waste stream — covered. We are missing training records for one member of your team on the Class II biosafety cabinet. That needs to be resolved before they touch it — I'll book them onto the next available slot, but it's three weeks out.",
        "I've reviewed the risk register. Manual handling assessed, electrical safety checked, chemical storage mapped. We are missing a spill response protocol specific to the solvent you're using — the generic one in the folder doesn't cover it. I'll write a one-pager. Also, the emergency shower nearest your bench is due for its quarterly test. I'll get that booked.",
      ],
      [
        "Timeline mapped. Sample prep: 2 days. Incubation: 72 hours (non-negotiable). Assay run: 1 day. Data processing: 1.5 days. Realistic total: 8 working days per round, assuming no instrument failures. We are missing buffer time for the plate reader booking — there's a 3-day queue on it right now. I'd add 4 days to the estimate. Start to first results: 12 working days minimum.",
        "I've built out the Gantt. Phase 1 (prep and aliquoting): 3 days. Phase 2 (treatment and incubation): 4 days. Phase 3 (analysis): 2 days. Phase 4 (repeat run): same again. We are missing an allowance for reagent delivery lead time — the primary antibody you need is currently 7–10 days shipping from the supplier. That shifts your start date by nearly two weeks. Order now.",
        "Timeline reviewed against current lab bookings. Here's the reality: the autoclave is out of service until Wednesday. The shared freezer block is at capacity until end of month. Accounting for those constraints — realistically 14 working days to first clean dataset. We are missing a contingency block for instrument downtime. I'd add 3 days. Nothing runs perfectly. Nothing.",
      ],
      [
        "Consumables check complete. Here is the confirmed stock list: 1.5 mL microtubes (500, sufficient), 96-well plates (24 in stock, need 12 more), 200 µL filter tips (2 boxes remaining — order 4 more), parafilm (half roll — fine). We are missing PVDF membrane for the western blot stage. Current stock is zero. Lead time is 4 days from usual supplier, 2 days express. I'd go express.",
        "I've gone through the consumables shelf. What's there: nitrile gloves in M and L (good), cryovials (sufficient), ethanol 70% (adequate). What's not there: the specific cell culture flasks you'll need for the expansion step — we have T-25s but you'll want T-75s. Also missing: sterile cell scrapers. Neither is exotic, both available on next-day delivery. I'll add to the standing order.",
        "Consumables audit done. Buffers: PBS and HEPES in stock, TBS needs making up (I'll do it). Staining reagents: DAPI in stock, secondary stain needs ordering. Slide covers: sufficient. We are missing mounting medium — last bottle was used on Tuesday and nobody reordered. It's a 2-day delivery. That's the one item that could hold up your staining workflow if you're not careful. I'm ordering it now.",
      ],
    ],
    signoff: "Alright. I've mapped the resources, flagged the risks, and allocated the budget. Faith has the final say on the vision side. Over to her.",
  },
  {
    id: 'faith',
    initial: 'F',
    name: 'Faith',
    role: 'Experiment Planner',
    moodPill: 'Editing mode',
    maxMessages: 4,
    headerBg: '#f6fff9',
    bubbleBg: '#f6fff9',
    bubbleBorder: '#9FE1CB',
    textColor: '#021a08',
    avatarBg: '#E1F5EE',
    avatarText: '#085041',
    nameColor: '#085041',
    signoffMessage: "This is it. This is your plan — tightened, clarified, and ready to go. Every section has been shaped by the three of us. Trust it. Now go do the work.",
    prompts: [
      'Sharpen the hypothesis wording',
      'Make the impact statement stronger',
      'Simplify the controls section',
      'Tighten the timeline language',
    ],
    responses: [
      [
        "Yes — let's sharpen that hypothesis. The bones are good but the wording is doing too much work at once. I'd suggest: lead with the mechanism, then the expected outcome, then the condition. Which part feels weakest to you right now — the claim or the justification?",
        "The hypothesis is close but it's still hedging. You don't need to protect yourself in the wording at this stage — Rachael already did that. What would you say if you had to explain it to a smart person at a dinner party? Start there, and we'll work backwards.",
        "Good instinct to revisit this. A strong hypothesis has one job: make a falsifiable prediction in plain language. Right now it's doing three things at once. Tell me the single most important claim and I'll help you build a cleaner sentence around it.",
      ],
      [
        "The impact statement needs a sharper landing. Right now it describes what the experiment does — what it needs to do is say why anyone should care. Try completing this sentence: 'If this works, it changes how we...' — finish that thought and we have something.",
        "Impact statements that start with 'This could potentially...' are immediately forgettable. You need a concrete, confident claim about the downstream effect. What is the best-case real-world outcome if your hypothesis is confirmed? Say it boldly — we can dial it back if needed.",
        "Let's make the impact land harder. Think about who reads this after you: the grant committee, the journal editors, the public. What is the single thing they need to understand? Lead with that. Everything else is detail.",
      ],
      [
        "The controls section is doing fine scientifically — Rachael made sure of that — but the language is dense. Let's break it into two parts: what you're holding constant, and what you're allowing to vary. Which is harder to explain clearly?",
        "Controls are where non-scientists get lost. You don't need to simplify the science — just the sentence structure. Can you rewrite the first sentence of this section as if you're handing it to a science journalist who has thirty seconds to read it?",
        "I'd suggest cutting the technical jargon from the controls section and replacing it with plain-language descriptions. The specifics live in your methods appendix — this plan is the narrative. What's the one sentence that captures what you're controlling for?",
      ],
      [
        "The timeline reads like a spreadsheet. That's fine for Eric's purposes but not for a plan document. Let's give it shape: a beginning, the critical path, and a completion milestone. What's the single most time-sensitive dependency in the whole experiment?",
        "Timelines with too many decimal-place estimates undermine confidence rather than building it. Round up, account for the unexpected, and frame phases as milestones rather than durations. What does 'done' look like at each stage? Name those moments and we have a much stronger section.",
        "Let's restructure the timeline as phases with clear gates rather than a flat list. What has to be true before each phase can begin? Answer that, and the timeline writes itself — and reads much more convincingly.",
      ],
    ],
    signoff: "This is it. This is your plan — tightened, clarified, and ready to go. Every section has been shaped by the three of us. Trust it. Now go do the work.",
  },
]

export function getCharacter(id: CharacterId): Character {
  return CHARACTERS.find(c => c.id === id)!
}

export function getNextCharacter(id: CharacterId): CharacterId | null {
  const idx = CHARACTERS.findIndex(c => c.id === id)
  if (idx < CHARACTERS.length - 1) return CHARACTERS[idx + 1].id
  return null
}

export function getContextualChips(
  id: CharacterId,
  messageCount: number,
  lastCharacterText: string,
  hasPapers: boolean,
  collectedPaperTitles: string[],
): string[] {
  if (id === 'rachael') {
    if (messageCount === 0) {
      return [
        'I want to test if ..',
        'My hypothesis is that low-dose treatment changes cellular response',
        'I think increasing temperature affects protein binding rate',
      ]
    }
    if (messageCount === 1 && hasPapers) {
      const topPaper = collectedPaperTitles[0] ?? 'the first paper'
      const secondPaper = collectedPaperTitles[1] ?? 'the second paper'
      return [
        `The most relevant is "${topPaper.length > 45 ? topPaper.slice(0, 45) + '…' : topPaper}"`,
        `Could you summarise "${secondPaper.length > 45 ? secondPaper.slice(0, 45) + '…' : secondPaper}"?`,
        'None of these match — I think this is genuinely novel',
        'Dive into these papers and pull out the key methodology',
      ]
    }
    if (messageCount === 2) {
      return [
        'Negative control: untreated sample; positive control: known activator',
        'I will hold temperature and pH constant and vary only concentration',
        'My controls are the vehicle-only and wildtype baseline groups',
      ]
    }
    if (messageCount === 3) {
      return [
        'If no dose-response curve emerges, the hypothesis is falsified',
        'A null result across all replicates would disprove the claim',
        'If the biomarker does not change, the mechanism is wrong',
      ]
    }
    if (messageCount === 4) {
      return [
        'Power analysis gives n=24 per group at 80% power, \u03b1=0.05',
        'Based on pilot data, n=12 per arm should detect a 20% effect',
        'Three biological replicates with three technical replicates each',
      ]
    }
    return ['Continue']
  }

  if (id === 'eric') {
    if (messageCount === 0) {
      return [
        'The inventory looks right — proceed with purchase orders',
        'We also need a flow cytometer for the analysis step',
        'Flag the missing micropipette set as urgent',
        'The -80\u00b0C capacity issue needs resolving before we start',
      ]
    }
    if (messageCount === 1) {
      return [
        'Budget looks reasonable — add the contingency line',
        'Can we make the buffers in-house to cut costs?',
        'The courier costs for offsite samples are around £60',
      ]
    }
    if (messageCount === 2) {
      return [
        'I can provide the CAS number for the fixative reagent',
        'Book the biosafety cabinet training slot — three weeks is fine',
        'The spill protocol gap needs addressing before day one',
      ]
    }
    if (messageCount === 3) {
      return [
        'Add four days buffer for the plate reader queue',
        'Order the primary antibody today — 7–10 day lead time',
        'Timeline looks realistic with the contingency block added',
      ]
    }
    if (messageCount === 4) {
      return [
        'Order PVDF membrane on express delivery',
        'Add T-75 flasks and sterile scrapers to the standing order',
        'Order mounting medium — mark as urgent',
      ]
    }
    return ['Confirmed']
  }

  if (id === 'faith') {
    if (messageCount === 0) {
      return [
        'Sharpen the hypothesis wording',
        'Make the impact statement stronger',
        'Simplify the controls section',
        'Tighten the timeline language',
      ]
    }
    if (messageCount === 1) {
      return [
        'Lead with the mechanism, then the expected outcome',
        'Here is a cleaner version: "X modulates Y via Z pathway"',
        'The justification is the weak part — I will rewrite it',
      ]
    }
    if (messageCount === 2) {
      return [
        '"If this works, it changes how we treat early-stage disease"',
        'The downstream effect is earlier, cheaper diagnostic screening',
        'This closes a critical gap in translational methodology',
      ]
    }
    if (messageCount === 3) {
      return [
        'Hold constant: temperature, pH, cell passage number',
        'Allow to vary: treatment concentration only',
        'One sentence version: we fix everything except the variable we are testing',
      ]
    }
    return [
      'Phase 1: prep and baseline — complete by end of week 2',
      'Critical path gate: reagents must arrive before phase 2 begins',
      'Done means three clean replicate datasets, not just one run',
    ]
  }

  return []
}
