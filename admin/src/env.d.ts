declare module '*.vue' {
  import type {DefineComponent} from 'vue'
  const component: DefineComponent<object, object, unknown>
  export default component
}

// swagger-ui-dist ships no types; the app uses only its bundle's constructor.
declare module 'swagger-ui-dist/swagger-ui-bundle.js' {
  const SwaggerUIBundle: (options: Record<string, unknown>) => unknown
  export default SwaggerUIBundle
}
