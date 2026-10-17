// Builds the 12-slide editable deck from docs/DECK.md and real captures.
// Run after the final report and captures are reconciled. Output is private until validated.
import fs from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
const skill = process.env.TP_PRESENTATION_SKILL;
const workspaceDir = process.env.TP_DECK_WORKSPACE;
const python = process.env.TP_RUNTIME_PYTHON;
if (!skill || !workspaceDir || !python) throw new Error('Set presentation skill, workspace and runtime Python paths');
const { importRuntimeModule } = await import(pathToFileURL(path.join(skill, 'container_tools/runtime_helpers.mjs')));
const { Presentation, PresentationFile } = await importRuntimeModule('@oai/artifact-tool');
const { resolvePresentationFont, finalizePresentation } = await import(pathToFileURL(path.join(skill, 'container_tools/artifact_tool_utils.mjs')));
const font = resolvePresentationFont();
console.log(`Presentation font: ${font}`);
const md = await fs.readFile('docs/DECK.md', 'utf8');
const sections = md.split(/^## Slide /m).slice(1).map(section => {
  const [heading, ...lines] = section.split('\n');
  return { title: heading.replace(/^\d+ — /, '').trim(), bullets: lines.filter(s => s.startsWith('- ')).map(s => s.slice(2)), note: lines.filter(s => s.startsWith('**Speaker note:**')).map(s => s.replace('**Speaker note:** ', '')).join('\n') };
});
if (sections.length !== 12 || sections.some(s => s.bullets.length !== 3)) throw new Error('Expected 12 slides and 3 points per slide');
const release = JSON.parse(await fs.readFile('docs/assets/release-data.json', 'utf8'));
const presentation = Presentation.create({ slideSize: { width: 1280, height: 720 } });
const colors = { ink: '#142D38', muted: '#536971', teal: '#087F7A', paper: '#F5F8F7', line: '#D7E3E0', white: '#FFFFFF' };
function text(slide, value, x, y, w, h, size = 24, color = colors.ink, bold = false) {
  const s = slide.shapes.add({ geometry: 'textbox', position: { left: x, top: y, width: w, height: h }, fill: 'none', line: { fill: 'none', width: 0, style: 'solid' } });
  s.text = value;
  s.text.style = { typeface: font, fontSize: size, color, bold };
  return s;
}
async function image(slide, filename, x, y, w, h) {
  const blob = new Uint8Array(await fs.readFile(path.join('docs/assets/screenshots', filename)));
  slide.images.add({ blob, contentType: 'image/png', alt: `Actual TrialPilot application: ${filename}`, fit: 'contain', position: { left: x, top: y, width: w, height: h } });
}
function table(slide, values, x, y, w, h, widths, size = 22) {
  const t = slide.tables.add({ rows: values.length, columns: values[0].length, left: x, top: y, width: w, height: h, columnWidths: widths, values });
  t.borders.assign({ fill: colors.line, width: 1, style: 'solid' });
  for (let r=0;r<values.length;r++) for(let c=0;c<values[0].length;c++) {
    const cell=t.getCell(r,c); cell.fill=r===0?colors.ink:(r%2===0?colors.paper:colors.white);
    cell.text.style={typeface:font,fontSize:size,color:r===0?colors.white:colors.ink,bold:r===0};
  }
  return t;
}
const capture = { 3:'03-protocol-review.png',4:'06-simulator-scenario.png',5:'08-provenance.png',6:'14-effect.png',7:'10-demo-approved.png',9:'16-validation.png' };
for (let i=0;i<sections.length;i++) {
  const n=i+1, s=sections[i], slide=presentation.slides.add();
  slide.background.fill=n===1||n===12?colors.ink:colors.paper;
  const dark=n===1||n===12;
  text(slide,'TRIALPILOT  /  HACKHARVARD 2026',56,30,1000,25,15,dark?'#77D4C6':colors.teal,true);
  text(slide,String(n).padStart(2,'0')+' / 12',1135,30,90,25,14,dark?'#CAD8DC':colors.muted);
  text(slide,s.title,56,83,1168,n===1?140:100,n===1?72:42,dark?colors.white:colors.ink,true);
  if(n===1) {
    text(slide,'Clinical trial choices.\nVisible assumptions.\nEvidence you can inspect.',58,253,1110,216,45,colors.white);
    text(slide,'Planning • synthetic operations • software validation',58,542,1100,45,27,'#77D4C6');
    text(slide,'MIT prototype  |  Local real-API demo  |  No production or clinical outcome claim',58,610,1130,44,18,'#CAD8DC');
  } else if(n===2) {
    text(slide,'$19.0m',60,210,620,125,94,colors.teal,true);
    text(slide,'Historical median estimated direct cost\nper pivotal trial',64,340,570,95,30);
    s.bullets.forEach((v,j)=>text(slide,v,710,220+j*122,500,110,26));
    text(slide,'138 trials • 59 approvals • 2015–2016 cohort\nMoore et al., JAMA Internal Medicine (2018)',64,540,1100,68,20,colors.muted);
  } else if(capture[n]) {
    s.bullets.forEach((v,j)=>text(slide,v,56,215+j*130,310,119,25));
    await image(slide,capture[n],390,190,834,478);
  } else if(n===8) {
    table(slide,[['kg CO2e','Published','Engine P50','P10–P90','Gap'],['CASPS','71,938.8','88,758.48','64,601–123,510','+23.38%'],['PRIMETIME','89,360.2','109,685.91','87,891–142,686','+22.75%']],56,205,1168,212,[180,205,215,358,210],24);
    text(slide,'Engine + library factors; excludes drug_supply extension',60,449,1150,45,26,colors.teal,true);
    text(slide,'Seed 7 • 2,000 draws • parameter set 1249d0f0eed8',60,499,1150,42,24);
    text(slide,'Paper arithmetic: +0.01% / −0.16%. Module gaps remain; range coverage is not model validation.',60,559,1140,64,23,colors.muted);
  } else if(n===10) {
    table(slide,[['Brief-provided challenge title','Demonstrated workflow'],['Choose Your Timeline','Version-bound scenarios + forecast assumptions'],['One Screen to Rule Them All','Synthetic site / country signals + interventions'],['Software Speedrun','Executed checks + downloadable evidence']],56,205,1168,330,[460,708],25);
    text(slide,'Original sponsor sheets were not supplied; title attribution remains unverified.',60,573,1130,55,24,colors.muted);
  } else if(n===11) {
    table(slide,[['Existing category','Example'],['Multi-metric design / carbon','Evinova; SHC / iLCCT calculator'],['Clinical monitoring','Medidata centralized monitoring / RBQM'],['Validation lifecycle','ValGenesis iVal']],56,205,1168,300,[500,668],25);
    text(slide,'Our focus: an inspectable MIT implementation connecting these workflows.',60,553,1130,74,28,colors.teal,true);
  } else if(n===12) {
    s.bullets.forEach((v,j)=>text(slide,v,60,220+j*120,1140,95,32,colors.white));
    text(slide,'Next: a permitted-data pilot with sponsor and site teams.',60,603,1140,44,28,'#77D4C6');
  }
  if(n!==1 && n!==12) text(slide,`Prototype • tested code ${release.tested_commit.slice(0,7)} • details and sources in speaker notes`,56,682,1160,23,13,colors.muted);
  slide.speakerNotes.text=s.note+'\n\nFull narrative and sources: docs/DECK.md. Evidence snapshot: '+release.validation_path+'. Science source: science/out/results.json at '+release.tested_commit+'. Captures are the actual local app with real API; operations are synthetic; identities are fictional demos.';
}
await fs.mkdir(path.join(workspaceDir,'.codex-finalizer'),{recursive:true});
await fs.mkdir(path.join(workspaceDir,'slides'),{recursive:true});
await fs.mkdir(path.join(workspaceDir,'output'),{recursive:true});
for(let i=0;i<12;i++) {
  const blob=await presentation.export({slide:presentation.slides.items[i],format:'png',scale:1});
  await fs.writeFile(path.join(workspaceDir,'slides',`slide-${String(i+1).padStart(2,'0')}.png`),new Uint8Array(await blob.arrayBuffer()));
  console.log(`Rendered ${i+1}/12`);
}
const candidatePath=path.join(workspaceDir,'.codex-finalizer','candidate.pptx');
await (await PresentationFile.exportPptx(presentation)).save(candidatePath);
const finalPath=path.join(workspaceDir,'output','trialpilot-deck.pptx');
const result=await finalizePresentation({workspaceDir,candidatePath,finalPath,pythonExecutable:python,integrityValidatorPath:path.join(skill,'container_tools/inspect_presentation_package_integrity.py'),layoutValidatorPath:path.join(skill,'container_tools/inspect_presentation_layout_geometry.py'),layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-bullet-geometry','--validate-heading-fit','--require-native-table-slide','8','--require-native-table-slide','10','--require-native-table-slide','11'],explicitTotalSlideCount:12,requiredNativeTableOwnerSlides:[8,10,11],requiredNativeChartOwnerSlides:[],fontPolicy:{basis:'design',families:[font]},verifyArtifactToolImport:true,receiptPath:path.join(workspaceDir,'.codex-finalizer','deck.validation.json')});
console.log(JSON.stringify({font,finalPath,result}));
