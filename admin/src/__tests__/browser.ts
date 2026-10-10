/**
 * Runs first, before any test file and before Vuetify is loaded: what Vuetify needs from a browser and jsdom
 * doesn't have (as in the BMU).
 */
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver = globalThis.ResizeObserver || ResizeObserverStub
window.matchMedia = window.matchMedia || ((query: string) => ({
  matches: false,
  media: query,
  onchange: null,
  addEventListener: () => {},
  removeEventListener: () => {},
  addListener: () => {},
  removeListener: () => {},
  dispatchEvent: () => false
}) as MediaQueryList)
globalThis.visualViewport = globalThis.visualViewport || Object.assign(new EventTarget(), {
  height: 768, offsetLeft: 0, offsetTop: 0, pageLeft: 0, pageTop: 0, scale: 1, width: 1024, onresize: null, onscroll: null, onscrollend: null
}) as VisualViewport
Element.prototype.scrollIntoView = Element.prototype.scrollIntoView || (() => {})
