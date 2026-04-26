'use client'

export interface Paper {
  title: string
  authors: string
  journal: string
  year: number
  similarity: number
  doi: string
  url: string
}

interface LiteratureCardProps {
  papers: Paper[]
}

export function LiteratureCard({ papers }: LiteratureCardProps) {
  return (
    <div style={{ background: '#faf9f7', border: '1px solid #e0ddd8', borderRadius: 12, overflow: 'hidden' }}>
      <div style={{ padding: '10px 14px', borderBottom: '1px solid #e0ddd8', display: 'flex', alignItems: 'center', gap: 8 }}>
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none" style={{ color: '#993C1D' }}>
          <rect x="1" y="1" width="12" height="12" rx="2" stroke="currentColor" strokeWidth="1.2" fill="none" />
          <path d="M3.5 4.5h7M3.5 7h7M3.5 9.5h4" stroke="currentColor" strokeWidth="1" strokeLinecap="round" />
        </svg>
        <span style={{ fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 10, color: '#555', letterSpacing: '0.05em', textTransform: 'uppercase' }}>
          Closest Literature QC matches
        </span>
        <span style={{ marginLeft: 'auto', fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 10, color: '#bbb' }}>
          {papers.length} results
        </span>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
        {papers.map((paper, i) => (
          <div key={i} style={{ padding: '10px 14px', borderBottom: i < papers.length - 1 ? '1px solid #f0ede8' : 'none' }}>
            <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8, marginBottom: 4 }}>
              <span style={{ fontFamily: 'var(--font-dm-sans)', fontSize: 12, color: '#1a1a1a', fontWeight: 500, lineHeight: 1.4, flex: 1 }}>
                {paper.title}
              </span>
              <div style={{ display: 'flex', alignItems: 'center', gap: 4, flexShrink: 0 }}>
                <div style={{ width: 36, height: 4, background: '#f0ede8', borderRadius: 2, overflow: 'hidden' }}>
                  <div style={{ width: `${paper.similarity}%`, height: '100%', background: '#993C1D', borderRadius: 2 }} />
                </div>
                <span style={{ fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 9, color: '#993C1D' }}>{paper.similarity}%</span>
              </div>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
              <span style={{ fontFamily: 'var(--font-dm-sans)', fontSize: 11, color: '#777' }}>
                {paper.authors} · {paper.journal} · {paper.year}
              </span>
              {paper.doi && (
                <span style={{ fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 9, color: '#bbb' }}>{paper.doi}</span>
              )}
              {paper.url && (
                <a href={paper.url} target="_blank" rel="noopener noreferrer"
                  style={{ fontFamily: 'var(--font-ibm-plex-mono)', fontSize: 9, color: '#185FA5', textDecoration: 'none' }}>
                  View protocol ↗
                </a>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

export const LITERATURE_POOLS: Paper[][] = [
  [
    { title: 'Temporal dynamics of gene expression following acute oxidative stress in mammalian cell lines', authors: 'Hargreaves M, Lin J, Osei-Bonsu K', journal: 'J. Cell Biol.', year: 2021, similarity: 91, doi: 'doi:10.1083/jcb.202009114', url: 'https://doi.org/10.1083/jcb.202009114' },
    { title: 'Dose-response relationships in antioxidant pathway activation: a systematic meta-analysis', authors: 'Varga L, Petrov A, Sundaram R', journal: 'Free Radic. Biol. Med.', year: 2022, similarity: 84, doi: 'doi:10.1016/j.freeradbiomed.2022.01.008', url: 'https://doi.org/10.1016/j.freeradbiomed.2022.01.008' },
    { title: 'Control strategies for confound mitigation in in-vitro stress assays', authors: 'Fletcher D, Nakagawa T', journal: 'PLOS ONE', year: 2020, similarity: 78, doi: 'doi:10.1371/journal.pone.0231476', url: 'https://doi.org/10.1371/journal.pone.0231476' },
    { title: 'Falsifiability criteria in translational biology: a methodological review', authors: 'Moberg S, Castillo RJ, Yuen HK', journal: 'Nat. Methods', year: 2023, similarity: 72, doi: 'doi:10.1038/s41592-022-01718-4', url: 'https://doi.org/10.1038/s41592-022-01718-4' },
  ],
  [
    { title: 'Confounding variable identification in high-throughput screening experiments', authors: 'Ishida T, Brennan OC, Mwangi P', journal: 'Sci. Rep.', year: 2022, similarity: 88, doi: 'doi:10.1038/s41598-022-14922-7', url: 'https://doi.org/10.1038/s41598-022-14922-7' },
    { title: 'Power analysis for small-n biological experiments: practical guidance', authors: 'Clements AS, Park JH', journal: 'BMC Bioinformatics', year: 2021, similarity: 82, doi: 'doi:10.1186/s12859-021-04045-3', url: 'https://doi.org/10.1186/s12859-021-04045-3' },
    { title: 'Replication crisis in cell biology: a quantitative perspective', authors: 'Tournadre N, Obi VE, Srinivasan A', journal: 'Cell Syst.', year: 2023, similarity: 75, doi: 'doi:10.1016/j.cels.2023.01.003', url: 'https://doi.org/10.1016/j.cels.2023.01.003' },
  ],
  [
    { title: 'Mechanistic basis of receptor-ligand dissociation kinetics under physiological flow', authors: 'Krüger RF, Wallis BT, Adesanya GO', journal: 'Biophys. J.', year: 2022, similarity: 93, doi: 'doi:10.1016/j.bpj.2022.05.014', url: 'https://doi.org/10.1016/j.bpj.2022.05.014' },
    { title: 'Negative control design in enzyme kinetics: overlooked best practices', authors: 'Stannard H, Chowdhury M, Leblanc P', journal: 'Biochemistry', year: 2020, similarity: 80, doi: 'doi:10.1021/acs.biochem.0c00231', url: 'https://doi.org/10.1021/acs.biochem.0c00231' },
    { title: 'Sample size determination in proteomics: effect size estimation and reproducibility', authors: 'Vassiliev AN, Kim DY, Reuter T', journal: 'J. Proteome Res.', year: 2021, similarity: 74, doi: 'doi:10.1021/acs.jproteome.0c00879', url: 'https://doi.org/10.1021/acs.jproteome.0c00879' },
    { title: 'Hypothesis-driven experimental design in molecular biology: a workshop synthesis', authors: 'Adeyemi OA, Croft PL, Zhang WL', journal: 'Mol. Cell', year: 2023, similarity: 69, doi: 'doi:10.1016/j.molcel.2023.02.019', url: 'https://doi.org/10.1016/j.molcel.2023.02.019' },
  ],
]
