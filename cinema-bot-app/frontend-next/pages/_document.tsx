import { Html, Head, Main, NextScript } from 'next/document';

export default function Document() {
  return (
    <Html lang="en">
      <Head>
        {/* Standard favicon */}
        <link rel="icon" href="/favicon.ico" sizes="any" />
        <link rel="icon" href="/favicon.svg" type="image/svg+xml" />
        
        {/* PNG favicons */}
        <link rel="icon" type="image/png" sizes="16x16" href="/favicon-16x16.png" />
        <link rel="icon" type="image/png" sizes="32x32" href="/favicon-32x32.png" />
        <link rel="icon" type="image/png" sizes="48x48" href="/favicon-48x48.png" />
        
        {/* Apple Touch Icons */}
        <link rel="apple-touch-icon" href="/favicon-192x192.png" />
        
        {/* Manifest */}
        <link rel="manifest" href="/manifest.json" />
        
        {/* Global styles */}
        <style>{`
          body {
            background-image: url('/CinemaChatBackground.png');
            background-size: contain;
            background-position: center;
            background-attachment: fixed;
            background-repeat: no-repeat;
            background-color: #f1ede9;
            min-height: 100vh;
            position: relative;
          }
          
          body::before {
            content: "";
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background-color: rgba(241, 237, 233, 0.6);
            z-index: -1;
          }
          
          /* Apply the same theme to containers and cards */
          .card, 
          .container,
          .card-body,
          .modal-content {
            background-color: rgba(241, 237, 233, 0.8) !important;
          }
        `}</style>
      </Head>
      <body>
        <Main />
        <NextScript />
      </body>
    </Html>
  );
}
