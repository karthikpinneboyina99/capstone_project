export default function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="bg-red-900/30 border border-red-700 text-red-300 rounded-lg p-4 text-sm">
      ⚠ {message}
    </div>
  )
}
