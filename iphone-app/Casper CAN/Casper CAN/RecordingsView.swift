//  RecordingsView.swift
//  Browse, share and delete recorded drives.
//
//  Sharing is the point: a CSV that cannot leave the phone is not evidence. The
//  share sheet gets it to AirDrop/Files, next to
//  ../../../experimentation/captures/journeys/ for comparison against the Mac
//  tools' own recordings of the same signals.

import SwiftUI

struct RecordingsView: View {
    let recorder: Recorder
    @Environment(\.dismiss) private var dismiss
    @State private var files: [URL] = []

    var body: some View {
        NavigationStack {
            Group {
                if files.isEmpty {
                    ContentUnavailableView {
                        Label("No recordings", systemImage: "folder")
                    } description: {
                        Text("Tap Record on the dashboard while connected.")
                    }
                } else {
                    List {
                        Section {
                            ForEach(files, id: \.self) { url in
                                row(for: url)
                            }
                            .onDelete(perform: delete)
                        } footer: {
                            Text(
                                "Columns match the wire frame, including a hex "
                                + "validity field — so a row records which signals "
                                + "the car actually answered, not just values."
                            )
                        }
                    }
                }
            }
            .navigationTitle("Recordings")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                }
            }
            // Refresh on appear rather than caching: the active recording grows
            // while this sheet is closed.
            .onAppear { files = Recorder.existingRecordings() }
        }
    }

    private func row(for url: URL) -> some View {
        let isActive = recorder.isRecording && recorder.currentURL == url
        return HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text(url.lastPathComponent)
                    .font(.subheadline)
                    .lineLimit(1)
                HStack(spacing: 6) {
                    if isActive {
                        Text("recording")
                            .foregroundStyle(.red)
                    }
                    Text(sizeDescription(of: url))
                }
                .font(.caption)
                .foregroundStyle(.secondary)
            }

            Spacer()

            ShareLink(item: url) {
                Image(systemName: "square.and.arrow.up")
            }
        }
    }

    private func sizeDescription(of url: URL) -> String {
        let size = (try? url.resourceValues(forKeys: [.fileSizeKey]))?.fileSize ?? 0
        return size.formatted(.byteCount(style: .file))
    }

    private func delete(at offsets: IndexSet) {
        for index in offsets {
            let url = files[index]
            // Refuse to delete the file currently being written; stopping first
            // is the user's call, not a side effect of a swipe.
            guard !(recorder.isRecording && recorder.currentURL == url) else { continue }
            try? FileManager.default.removeItem(at: url)
        }
        files = Recorder.existingRecordings()
    }
}

#Preview {
    RecordingsView(recorder: Recorder())
}
