import React from 'react';
import { Search, ChevronDown, Check, Database, FileStack } from 'lucide-react';
import { ProjectInfo, PageView } from '../../types';
import type { ApiHealth } from '../../api/client';

interface TopBarProps {
  projects: ProjectInfo[];
  selectedProject: ProjectInfo | null;
  onSelectProject: (proj: ProjectInfo) => void;
  currentPage: PageView;
  caseLabel?: string;
  onSearchCase: (query: string) => void;
  searchMessage: string | null;
  health: ApiHealth | null;
}

export const TopBar: React.FC<TopBarProps> = ({
  projects,
  selectedProject,
  onSelectProject,
  currentPage,
  caseLabel,
  onSearchCase,
  searchMessage,
}) => {
  const [dropdownOpen, setDropdownOpen] = React.useState(false);
  const [searchQuery, setSearchQuery] = React.useState('');

  const pageNames: Record<PageView, string> = {
    dashboard: 'Overview',
    'high-risk-cases': 'High-Risk Cases',
    'case-details': caseLabel ? `Case ${caseLabel}` : 'Acquisition Cases',
    'risk-explanation': caseLabel ? `Risk Analysis · Case ${caseLabel}` : 'Risk Analysis',
    'recommended-actions': caseLabel ? `Recommended Actions · Case ${caseLabel}` : 'Recommended Actions',
    'gis-map': 'GIS Parcel Map',
    reports: 'Executive Briefing',
    chat: 'Ask the Documents',
    ingestion: 'Data & Analysis Jobs',
  };

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (searchQuery.trim()) onSearchCase(searchQuery.trim());
  };

  const isDemo = selectedProject?.isDemo ?? false;

  return (
    <header className="sticky top-0 z-30 h-16 shrink-0 bg-white border-b border-slate-200">
      <div className="h-full px-6 flex items-center justify-between gap-4">
        <div className="flex items-center gap-4 min-w-0">
          <div className="relative">
            <button
              onClick={() => setDropdownOpen(!dropdownOpen)}
              aria-haspopup="listbox"
              aria-expanded={dropdownOpen}
              className="flex items-center gap-2 rounded-md px-2.5 py-1.5 text-left hover:bg-slate-100 transition-colors"
            >
              <div className="min-w-0">
                <div className="text-[13px] font-semibold text-slate-900 truncate max-w-56">{selectedProject?.name ?? 'Loading…'}</div>
                <div className="text-[11px] text-slate-500">
                  <span className="font-mono">{selectedProject?.code}</span>
                  {selectedProject && <span> · {selectedProject.totalCases.toLocaleString()} cases</span>}
                </div>
              </div>
              <ChevronDown className="h-4 w-4 text-slate-400 shrink-0" />
            </button>

            {dropdownOpen && (
              <div className="absolute top-full left-0 mt-1 w-80 bg-white rounded-lg shadow-lg border border-slate-200 py-1 z-50">
                <div className="px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.1em] text-slate-400">Projects</div>
                {projects.map((proj) => (
                  <button
                    key={proj.id}
                    onClick={() => {
                      onSelectProject(proj);
                      setDropdownOpen(false);
                    }}
                    className={`w-full text-left px-3 py-2 text-xs transition-colors flex items-center justify-between gap-2 ${
                      proj.id === selectedProject?.id ? 'bg-slate-50' : 'hover:bg-slate-50'
                    }`}
                  >
                    <div className="min-w-0">
                      <div className="font-medium text-slate-900 truncate">{proj.name}</div>
                      <div className="text-[11px] text-slate-500">
                        <span className="font-mono">{proj.code}</span> · {proj.isDemo ? 'Synthetic demo data' : 'Uploaded records'}
                      </div>
                    </div>
                    {proj.id === selectedProject?.id && <Check className="h-4 w-4 text-blue-600 shrink-0" />}
                  </button>
                ))}
              </div>
            )}
          </div>

          <div className="hidden md:block h-6 w-px bg-slate-200" />
          <h1 className="hidden md:block text-[15px] font-semibold text-slate-900 truncate">{pageNames[currentPage]}</h1>
        </div>

        <div className="flex items-center gap-3">
          {selectedProject &&
            (isDemo ? (
              <span className="hidden sm:inline-flex items-center gap-1.5 text-[11px] font-medium text-amber-700 bg-amber-50 border border-amber-200 px-2 py-1 rounded-md">
                <Database className="h-3.5 w-3.5" /> Synthetic demo data
              </span>
            ) : (
              <span className="hidden sm:inline-flex items-center gap-1.5 text-[11px] font-medium text-slate-600 bg-slate-50 border border-slate-200 px-2 py-1 rounded-md">
                <FileStack className="h-3.5 w-3.5" /> Uploaded records
              </span>
            ))}

          <div className="relative">
            <form onSubmit={handleSearch} className="relative w-64">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
              <input
                type="text"
                placeholder="Search case, village or survey no."
                aria-label="Search cases"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full pl-8 pr-3 py-1.5 text-[13px] bg-white border border-slate-200 rounded-md text-slate-800 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-colors"
              />
            </form>
            {searchMessage && (
              <div role="status" className="absolute right-0 top-full mt-1 w-64 text-xs bg-slate-900 text-white px-3 py-2 rounded-md shadow-lg">
                {searchMessage}
              </div>
            )}
          </div>
        </div>
      </div>
    </header>
  );
};
