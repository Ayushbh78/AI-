/* Flashcards for rote learning: see the question, say the answer, flip, mark it. Missed cards come back. */
(function () {
  const U = window.U;

  function mount(box, cards) {
    const total = cards.length;
    let queue, known, shown;

    function reset() {
      queue = cards.map(function (_, i) { return i; });
      known = 0;
      shown = false;
      render();
    }

    function render() {
      if (!queue.length) {
        box.innerHTML = '<p><strong>All ' + total + ' cards recalled.</strong> Now run the check below to test it.</p>' +
          '<button type="button" class="btn" data-act="restart">Go through them again</button>';
      } else {
        const card = cards[queue[0]];
        box.innerHTML =
          '<p class="small muted">Recalled ' + known + ' of ' + total + '. Cards left: ' + queue.length + '</p>' +
          '<div class="flashcard"><div class="fc-q">' + U.esc(card[0]) + '</div>' +
          (shown ? '<div class="fc-a">' + U.esc(card[1]) + '</div>'
                 : '<div class="fc-hint small muted">Say the answer aloud before you look.</div>') + '</div>' +
          '<div class="fc-actions">' + (shown
            ? '<button type="button" class="btn primary" data-act="got">I knew it</button><button type="button" class="btn" data-act="again">Show again later</button>'
            : '<button type="button" class="btn primary" data-act="show">Show answer</button>') + '</div>';
      }
      box.querySelectorAll("[data-act]").forEach(function (btn) {
        btn.addEventListener("click", function () { act(btn.dataset.act); });
      });
    }

    function act(name) {
      if (name === "show") { shown = true; }
      else if (name === "got") { queue.shift(); known++; shown = false; }
      else if (name === "again") { const first = queue.shift(); queue.splice(Math.min(3, queue.length), 0, first); shown = false; }
      else if (name === "restart") { reset(); return; }
      render();
    }

    reset();
  }

  window.Rote = { mount: mount };
})();
