import { MarketDataProvider } from "./components/MarketDataContext";
import Shell from "./components/Shell";
import "./globals.css";

export const metadata = {
  title: "India Market Master",
  description: "Local market intelligence desk",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>
        <MarketDataProvider>
          <Shell>{children}</Shell>
        </MarketDataProvider>
      </body>
    </html>
  );
}

