import { useCallback, useEffect, useState } from 'react';
import { PageView, ProjectInfo, AcquisitionCase, RiskTrendPoint } from './types';
import { api, ApiHealth, FeatureCollection } from './api/client';
import { toCase, toProject, withDetail } from './api/adapter';
import { Sidebar } from './components/layout/Sidebar';
import { TopBar } from './components/layout/TopBar';
import { EmptyState } from './components/common/EmptyState';
import { DashboardView } from './components/pages/DashboardView';
import { HighRiskCasesView } from './components/pages/HighRiskCasesView';
import { CaseDetailsView } from './components/pages/CaseDetailsView';
import { RiskExplanationView } from './components/pages/RiskExplanationView';
import { RecommendedActionsView } from './components/pages/RecommendedActionsView';
import { GisMapView } from './components/pages/GisMapView';
import { ReportsView } from './components/pages/ReportsView';
import { IngestionView } from './components/pages/IngestionView';
import { ChatView } from './components/pages/ChatView';

const HERO_CASE_ID = '#0472';
const CASE_PAGES: PageView[] = ['case-details', 'risk-explanation', 'recommended-actions'];

export function App() {
  const [currentPage, setCurrentPage] = useState<PageView>('dashboard');
  const [projects, setProjects] = useState<ProjectInfo[]>([]);
  const [projectId, setProjectId] = useState<string | null>(null);
  const [cases, setCases] = useState<AcquisitionCase[]>([]);
  const [trend, setTrend] = useState<RiskTrendPoint[]>([]);
  const [features, setFeatures] = useState<FeatureCollection | null>(null);
  const [selectedCase, setSelectedCase] = useState<AcquisitionCase | null>(null);
  const [health, setHealth] = useState<ApiHealth | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [searchMessage, setSearchMessage] = useState<string | null>(null);

  const project = projects.find((p) => p.id === projectId) ?? null;

  const loadProjects = useCallback(async (selectId?: string) => {
    try {
      const [list, h] = await Promise.all([api.projects(), api.health().catch(() => null)]);
      const summaries = await Promise.all(list.map((p) => api.summary(p.project_id).catch(() => undefined)));
      const infos = list.map((p, i) => toProject(p, summaries[i]));
      setProjects(infos);
      setHealth(h);
      setProjectId((current) => selectId ?? current ?? infos[0]?.id ?? null);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load projects.');
    }
  }, []);

  const loadProjectData = useCallback(async (id: string) => {
    setLoading(true);
    try {
      const [summary, rawCases, fc] = await Promise.all([api.summary(id), api.cases(id), api.mapFeatures(id)]);
      const mapped = rawCases.map((c) => toCase(c, fc.features));
      setCases(mapped);
      setFeatures(fc);
      setTrend(summary.trend ?? []);
      setProjects((prev) => prev.map((p) => (p.id === id ? { ...p, ...toProject({
        project_id: p.id, name: p.name, corridor_id: p.code, description: p.description, is_demo: p.isDemo, created_at: '',
      }, summary) } : p)));
      setSelectedCase((prev) =>
        mapped.find((c) => c.uid === prev?.uid) ?? mapped.find((c) => c.id === HERO_CASE_ID) ?? mapped[0] ?? null,
      );
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load project data.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadProjects();
  }, [loadProjects]);

  useEffect(() => {
    if (projectId) void loadProjectData(projectId);
  }, [projectId, loadProjectData]);

  // Evidence (facts, conflicts) for an uploaded-data case is fetched when it is selected.
  const selectedUid = selectedCase?.uid;
  const selectedSynthetic = selectedCase?.isSynthetic;
  useEffect(() => {
    if (!selectedUid || selectedSynthetic) return;
    let cancelled = false;
    api.caseDetail(selectedUid)
      .then((detail) => {
        if (!cancelled) setSelectedCase((prev) => (prev && prev.uid === selectedUid ? withDetail(prev, detail) : prev));
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [selectedUid, selectedSynthetic]);

  const handleSearchCase = (query: string) => {
    const q = query.toLowerCase().replace(/^#?/, '#');
    const plain = query.toLowerCase();
    const matched = cases.find(
      (c) => c.id.toLowerCase() === q || c.villageName.toLowerCase().includes(plain) || c.surveyNo.toLowerCase().includes(plain),
    );
    if (matched) {
      setSelectedCase(matched);
      setCurrentPage('case-details');
      setSearchMessage(null);
    } else {
      setSearchMessage(`No case matches "${query}" in this project.`);
      setTimeout(() => setSearchMessage(null), 4000);
    }
  };

  const handleNavigate = (page: PageView) => {
    setCurrentPage(page);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const highRiskCount = cases.filter((c) => c.riskCategory === 'HIGH').length;

  const renderPage = () => {
    if (error && !project) return <EmptyState title="Backend unavailable" message={error} />;
    if (!project) return <EmptyState title="Loading" message="Loading projects…" />;
    if (currentPage === 'ingestion') {
      return (
        <IngestionView
          project={project}
          onProjectCreated={(id) => {
            void loadProjects(id);
          }}
          onDataChanged={() => {
            void loadProjects(project.id);
            void loadProjectData(project.id);
          }}
          onOpenCases={() => handleNavigate('high-risk-cases')}
        />
      );
    }
    if (currentPage === 'chat') return <ChatView key={project.id} project={project} cases={cases} onNavigate={handleNavigate} />;
    if (loading && cases.length === 0) return <EmptyState title="Loading" message="Loading cases…" />;
    if (cases.length === 0) {
      return (
        <EmptyState
          title="No cases yet"
          message="This project has no analysed cases. Upload PDFs and GIS files and run an analysis job."
          action={{ label: 'Open Data & Analysis Jobs', onClick: () => handleNavigate('ingestion') }}
        />
      );
    }
    const current = selectedCase ?? cases[0];
    switch (currentPage) {
      case 'dashboard':
        return <DashboardView project={project} cases={cases} trend={trend} onNavigate={handleNavigate} onSelectCase={setSelectedCase} />;
      case 'high-risk-cases':
        return <HighRiskCasesView project={project} cases={cases} onSelectCase={setSelectedCase} onNavigate={handleNavigate} />;
      case 'case-details':
        return <CaseDetailsView caseData={current} project={project} onNavigate={handleNavigate} />;
      case 'risk-explanation':
        return <RiskExplanationView caseData={current} onNavigate={handleNavigate} />;
      case 'recommended-actions':
        return <RecommendedActionsView key={current.uid} caseData={current} onNavigate={handleNavigate} />;
      case 'gis-map':
        return (
          <GisMapView
            project={project}
            cases={cases}
            features={features}
            selectedCase={current}
            onSelectCase={setSelectedCase}
            onNavigate={handleNavigate}
          />
        );
      case 'reports':
        return <ReportsView project={project} cases={cases} health={health} onNavigate={handleNavigate} />;
      default:
        return null;
    }
  };

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-slate-50 font-sans text-slate-900">
      <Sidebar currentPage={currentPage} onNavigate={handleNavigate} highRiskCount={highRiskCount} health={health} project={project} />

      <div className="flex-1 flex flex-col h-full overflow-hidden">
        <TopBar
          projects={projects}
          selectedProject={project}
          onSelectProject={(p) => {
            setProjectId(p.id);
            setSelectedCase(null);
            setCases([]);
          }}
          currentPage={currentPage}
          caseLabel={CASE_PAGES.includes(currentPage) ? selectedCase?.id : undefined}
          onSearchCase={handleSearchCase}
          searchMessage={searchMessage}
          health={health}
        />

        <main className="flex-1 overflow-y-auto px-6 py-6 max-w-7xl w-full mx-auto">
          {error && project && (
            <div className="mb-4 p-3 rounded-xl bg-rose-50 border border-rose-200 text-xs text-rose-800">{error}</div>
          )}
          {renderPage()}
        </main>
      </div>
    </div>
  );
}

export default App;
