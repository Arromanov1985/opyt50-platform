/* Release 0.9 — homepage shortcuts. Keeps existing job-search APIs untouched. */
'use strict';
document.addEventListener('DOMContentLoaded', () => {
  const byId=id=>document.getElementById(id);
  const profession=byId('profession-filter');
  const jobs=byId('jobs');
  const runSearch=()=>{
    byId('jobs-filter')?.click();
    jobs?.scrollIntoView({behavior:'smooth',block:'start'});
  };

  const heroQuery=byId('hero-job-query');
  byId('hero-job-search')?.addEventListener('click',()=>{
    if(profession && heroQuery) profession.value=heroQuery.value.trim();
    runSearch();
  });
  heroQuery?.addEventListener('keydown',event=>{
    if(event.key!=='Enter') return;
    event.preventDefault();
    if(profession) profession.value=heroQuery.value.trim();
    runSearch();
  });

  document.querySelectorAll('[data-job-query]').forEach(card=>{
    card.addEventListener('click',event=>{
      event.preventDefault();
      if(profession) profession.value=card.dataset.jobQuery || '';
      runSearch();
    });
  });

  const advanced=byId('jobs-advanced');
  if (advanced && window.matchMedia('(max-width: 620px)').matches) advanced.open=false;
  const counter=byId('advanced-filter-count');
  const advancedIds=['salary-filter','schedule-filter','employment-filter','sort-filter'];
  function updateAdvancedCount(){
    let count=0;
    if(Number(byId('salary-filter')?.value||0)>0) count++;
    if(byId('schedule-filter')?.value) count++;
    if(byId('employment-filter')?.value) count++;
    if((byId('sort-filter')?.value||'recent')!=='recent') count++;
    if(counter){
      counter.textContent=String(count);
      counter.classList.toggle('is-visible',count>0);
    }
    if(count>0 && advanced) advanced.open=true;
  }
  advancedIds.forEach(id=>{
    byId(id)?.addEventListener('change',updateAdvancedCount);
    byId(id)?.addEventListener('input',updateAdvancedCount);
  });
  byId('jobs-reset')?.addEventListener('click',()=>setTimeout(updateAdvancedCount,0));
  updateAdvancedCount();
});
