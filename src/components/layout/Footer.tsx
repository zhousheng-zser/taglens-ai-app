export function Footer() {
  return (
    <footer className="py-6 px-4 sm:px-6 lg:px-8 border-t border-border/40 mt-12">
      <div className="container mx-auto text-center text-sm text-muted-foreground">
        <p>&copy; {new Date().getFullYear()} TagLens AI. 保留所有权利。</p>
      </div>
    </footer>
  );
}
