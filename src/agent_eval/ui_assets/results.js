(() => {
  const model = document.getElementById('model');
  const protection = document.getElementById('protection');
  const cards = Array.from(document.querySelectorAll('.model-card[data-model]'));
  const update = () => {
    let visible = 0;
    for (const card of cards) {
      card.hidden = Boolean((model.value && card.dataset.model !== model.value) || card.dataset.condition !== protection.value);
      if (!card.hidden) visible++;
    }
    document.getElementById('empty').hidden = visible > 0 || cards.length === 0;
  };
  model.addEventListener('change', update);
  protection.addEventListener('change', update);
  update();
})();
