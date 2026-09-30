declare module "jest-axe" {
  import type { AxeResults, RunOptions, Spec } from "axe-core";

  export function axe(
    html: Element | string,
    options?: RunOptions,
  ): Promise<AxeResults>;

  export function configureAxe(
    options?: RunOptions & { globalOptions?: Spec },
  ): typeof axe;
}
