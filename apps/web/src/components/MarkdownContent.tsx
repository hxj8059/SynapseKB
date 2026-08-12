import rehypeSanitize from "rehype-sanitize";
import ReactMarkdown from "react-markdown";
import { PrismLight as SyntaxHighlighter } from "react-syntax-highlighter";
import bash from "react-syntax-highlighter/dist/esm/languages/prism/bash";
import json from "react-syntax-highlighter/dist/esm/languages/prism/json";
import markdown from "react-syntax-highlighter/dist/esm/languages/prism/markdown";
import python from "react-syntax-highlighter/dist/esm/languages/prism/python";
import sql from "react-syntax-highlighter/dist/esm/languages/prism/sql";
import typescript from "react-syntax-highlighter/dist/esm/languages/prism/typescript";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";
import remarkGfm from "remark-gfm";

SyntaxHighlighter.registerLanguage("bash", bash);
SyntaxHighlighter.registerLanguage("shell", bash);
SyntaxHighlighter.registerLanguage("json", json);
SyntaxHighlighter.registerLanguage("markdown", markdown);
SyntaxHighlighter.registerLanguage("python", python);
SyntaxHighlighter.registerLanguage("sql", sql);
SyntaxHighlighter.registerLanguage("typescript", typescript);
SyntaxHighlighter.registerLanguage("javascript", typescript);
SyntaxHighlighter.registerLanguage("tsx", typescript);
SyntaxHighlighter.registerLanguage("jsx", typescript);

export function MarkdownContent({ children }: { children: string }) {
  return (
    <div className="markdown-content text-sm leading-8">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeSanitize]}
        components={{
          a: ({ children: label, ...props }) => (
            <a {...props} rel="noreferrer" target="_blank">
              {label}
            </a>
          ),
          code: ({ className, children: code, ...props }) => {
            const language = /language-([\w-]+)/.exec(className ?? "")?.[1];
            const value = String(code).replace(/\n$/, "");
            if (language) {
              return (
                <SyntaxHighlighter
                  language={language}
                  style={oneDark}
                  customStyle={{ margin: "1rem 0", borderRadius: "0.75rem" }}
                  PreTag="div"
                >
                  {value}
                </SyntaxHighlighter>
              );
            }
            return (
              <code className={className} {...props}>
                {code}
              </code>
            );
          },
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
