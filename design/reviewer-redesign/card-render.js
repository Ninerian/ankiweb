/*
 * Shared card model + renderer for mockup.html (reviewer) and editor-mockup.html (editor preview/stack).
 * Card: { front: string, hint?: string, back: string, example?: string }
 * hint/example are optional; empty/missing => not rendered.
 * example is plain text; wrap the key word in *asterisks* to highlight it as <mark>.
 */
(function (global) {
  'use strict';

  function escapeHtml(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  // Escape first, then turn *word* into <mark>word</mark>.
  function renderExample(example) {
    return escapeHtml(example).replace(/\*([^*\n]+)\*/g, '<mark>$1</mark>');
  }

  function hasText(value) {
    return typeof value === 'string' && value.trim() !== '';
  }

  // Returns { front, hint, back, example } as safe HTML strings ('' when absent).
  function renderCard(card) {
    return {
      front: escapeHtml(card.front),
      hint: hasText(card.hint) ? escapeHtml(card.hint) : '',
      back: escapeHtml(card.back),
      example: hasText(card.example) ? renderExample(card.example) : ''
    };
  }

  global.CardRender = { escapeHtml: escapeHtml, renderCard: renderCard, hasText: hasText };
})(window);
