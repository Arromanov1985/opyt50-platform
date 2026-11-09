/* Release 0.9 — auth affordances and vacancy progress */
'use strict';
(() => {
  const $=(sel,root=document)=>root.querySelector(sel);

  function setAuthMessage(text=''){
    const el=$('#auth-message');
    if(el) el.textContent=text;
  }

  document.addEventListener('click',event=>{
    const toggle=event.target.closest('#password-toggle');
    if(toggle){
      const input=$('#auth-password');
      if(!input) return;
      const show=input.type==='password';
      input.type=show?'text':'password';
      toggle.textContent=show?'Скрыть':'Показать';
      toggle.setAttribute('aria-pressed',String(show));
      input.focus();
      return;
    }
    if(event.target.closest('[data-role],[data-switch],#login-open,#register-open,[data-register]')){
      setAuthMessage('');
    }
  });

  document.addEventListener('input',event=>{
    if(event.target.closest('#auth-form')) setAuthMessage('');
  });

  function fieldFilled(form,name){
    const field=form.elements.namedItem(name);
    return Boolean(field && String(field.value||'').trim());
  }
  function validSalary(form){
    const min=Number(form.elements.namedItem('salary_min')?.value);
    const max=Number(form.elements.namedItem('salary_max')?.value);
    return Number.isFinite(min)&&Number.isFinite(max)&&min>=0&&max>=min;
  }
  function updateVacancyProgress(form){
    if(!form || form.id!=='vacancy-form') return;
    const legacy=form.dataset.editMode==='legacy';
    const step1=fieldFilled(form,'title')&&fieldFilled(form,'city')&&validSalary(form);
    const step2=legacy
      ? fieldFilled(form,'legacy_description')
      : fieldFilled(form,'responsibilities')&&fieldFilled(form,'requirements')&&fieldFilled(form,'conditions');
    const preview=form.querySelector('#vacancy-preview');
    const step3=Boolean(preview && !preview.hidden);
    const publish=form.querySelector('#vacancy-publish');
    const ready=Boolean(publish && !publish.disabled);
    const done=[step1,step2,step3,false];
    let current=!step1?0:!step2?1:!step3?2:3;
    form.querySelectorAll('.vacancy-progress-step').forEach((el,index)=>{
      el.classList.toggle('is-done',done[index]);
      el.classList.toggle('is-current',index===current);
      const icon=el.querySelector('i');
      if(icon) icon.textContent=done[index]?'✓':String(index+1);
    });
    const percent=step3?100:step2?66:step1?33:0;
    const bar=form.querySelector('#vacancy-progress-bar');
    if(bar) bar.style.width=percent+'%';
    const label=form.querySelector('#vacancy-progress-label');
    if(label) label.textContent=ready?'Готово к публикации':percent+'% заполнено';
    form.querySelector('.vacancy-publish-actions')?.classList.toggle('is-ready',ready);

    form.querySelectorAll('textarea[maxlength]').forEach(area=>{
      const counter=area.closest('.field')?.querySelector('.vacancy-field-counter');
      if(counter) counter.textContent=area.value.length+' / '+area.maxLength;
    });
  }

  function enhanceVacancyForm(form){
    if(!form || form.dataset.progressEnhanced==='1') return;
    form.dataset.progressEnhanced='1';
    form.querySelectorAll('textarea[maxlength]').forEach(area=>{
      const label=area.closest('.field')?.querySelector('label');
      if(label && !label.querySelector('.vacancy-field-counter')){
        const counter=document.createElement('span');
        counter.className='vacancy-field-counter';
        label.append(counter);
      }
    });
    updateVacancyProgress(form);
  }

  document.addEventListener('input',event=>{
    const form=event.target.closest?.('#vacancy-form');
    if(form) updateVacancyProgress(form);
  });
  document.addEventListener('change',event=>{
    const form=event.target.closest?.('#vacancy-form');
    if(form) updateVacancyProgress(form);
  });
  document.addEventListener('click',event=>{
    if(event.target.closest('#vacancy-show-preview')){
      setTimeout(()=>{
        const form=event.target.closest('#vacancy-form');
        updateVacancyProgress(form);
      },0);
    }
  });

  const observer=new MutationObserver(()=>{
    const form=$('#vacancy-form');
    if(form) enhanceVacancyForm(form);
  });
  observer.observe(document.body,{childList:true,subtree:true});
  document.addEventListener('DOMContentLoaded',()=>{
    const form=$('#vacancy-form');
    if(form) enhanceVacancyForm(form);
  });

  window.StazhnoForms={setAuthMessage,updateVacancyProgress};
})();
