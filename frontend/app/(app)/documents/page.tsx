import UploadDropzone from "@/components/documents/UploadDropzone";
import DocumentList from "@/components/documents/DocumentList";

export default function DocumentsPage() {
  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <div className="inline-flex items-center gap-2 rounded-full bg-surface-muted px-2.5 py-1 text-xs font-semibold uppercase tracking-wider text-muted">
          <span className="h-1.5 w-1.5 rounded-full bg-primary" />
          Document library
        </div>
        <h1 className="font-heading text-2xl font-semibold tracking-tight text-foreground">
          Documents
        </h1>
        <p className="max-w-2xl text-base text-muted">
          Upload a PDF to add it to your library. Once it finishes
          processing, head to Chat to start asking it questions.
        </p>
      </div>

      <UploadDropzone />
      <DocumentList />
    </div>
  );
}
