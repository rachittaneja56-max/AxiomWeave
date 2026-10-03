import ReactMarkdown from "react-markdown";
import { markdownWithoutDuplicateHeading } from "./markdownUtils";

export function MarkdownDocument({
  content,
  suppressFirstHeading,
}: {
  content: string;
  suppressFirstHeading?: string;
}) {
  const renderedContent = suppressFirstHeading
    ? markdownWithoutDuplicateHeading(content, suppressFirstHeading)
    : content;
  return (
    <div className="markdown-document">
      <ReactMarkdown
        components={{
          a: ({ href, children, ...props }) => {
            const external = Boolean(href && /^https?:\/\//i.test(href));
            return (
              <a
                href={href}
                {...props}
                target={external ? "_blank" : undefined}
                rel={external ? "noreferrer" : undefined}
              >
                {children}
              </a>
            );
          },
        }}
      >
        {renderedContent}
      </ReactMarkdown>
    </div>
  );
}
