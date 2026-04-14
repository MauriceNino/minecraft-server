import defaultMdxComponents from 'fumadocs-ui/mdx';
import type { MDXComponents } from 'mdx/types';
import { ImageZoom } from 'fumadocs-ui/components/image-zoom';

export function getMDXComponents(components?: MDXComponents) {
  return {
    ...defaultMdxComponents,
    img: (props: React.ImgHTMLAttributes<HTMLImageElement>) => {
      const { src, ...rest } = props;
      const basePath = process.env.NEXT_PUBLIC_BASE_PATH || '';

      const prefixStringUrl = (url: string) => (url.startsWith('/') ? `${basePath}${url}` : url);
      const newSrc =
        typeof src === 'string'
          ? prefixStringUrl(src)
          : src && 'src' in src && typeof src.src === 'string'
            ? { ...src, src: prefixStringUrl(src.src) }
            : src;

      return <ImageZoom src={newSrc as any} {...rest} />;
    },
    ...components,
  } satisfies MDXComponents;
}

export const useMDXComponents = getMDXComponents;

declare global {
  type MDXProvidedComponents = ReturnType<typeof getMDXComponents>;
}
