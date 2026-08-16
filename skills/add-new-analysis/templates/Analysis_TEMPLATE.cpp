//   GAMBIT: Global and Modular BSM Inference Tool
//   *********************************************
///
///  Analysis_<EXPT>_<GROUP>_<YYYY>_<NN>
///
///  Recast of <EXPT> <analysis code>: <one-line title>
///  Paper: arXiv:XXXX.XXXXX  (InspireID: XXXXXXX)
///  Luminosity: <L> fb^-1, sqrt(s) = <E> TeV
///
///  *********************************************
///
///  Authors (add name and date if you modify):
///
///  \author <Your Name>
///          (<email>)
///  \date <YYYY> <Mon>
///
///  *********************************************

#include <vector>
#include <cmath>

#include "gambit/ColliderBit/analyses/Analysis.hpp"
#include "gambit/ColliderBit/analyses/AnalysisMacros.hpp"
#include "gambit/ColliderBit/ATLASEfficiencies.hpp"   // or CMSEfficiencies.hpp
#include "gambit/ColliderBit/analyses/Cutflow.hpp"
// #include "gambit/ColliderBit/mt2_bisect.h"         // if MT2 needed
// #include "METSignificance/METSignificance.hpp"     // if MET significance needed

namespace Gambit
{
  namespace ColliderBit
  {

    class Analysis_TEMPLATE : public Analysis
    {
    private:

      struct ptComparison
      {
        bool operator() (const HEPUtils::Particle* i, const HEPUtils::Particle* j)
        { return (i->pT() > j->pT()); }
      } comparePt;

    public:

      // Required detector sim: "ATLAS", "CMS" or "Identity"
      static constexpr const char* detector = "ATLAS";

      Analysis_TEMPLATE()
      {
        set_analysis_name("TEMPLATE");          // must equal the registered name
        set_luminosity(139.);                   // fb^-1, from the paper
        // set_bkgjson("ColliderBit/data/analyses_json_files/TEMPLATE_bkgonly.json");

        // One per signal region; cut strings are documentation shown in cutflows
        DEFINE_SIGNAL_REGION("SR-A", "preselection", "njets >= 2", "met > 200")
        DEFINE_SIGNAL_REGION("SR-B", "preselection", "njets >= 4", "met > 300")

        // Optional histograms
        // DEFINE_HISTOGRAM_1D_UNIFORM("met", 20, 0., 1000., "E_T^{miss} [GeV]")
      }

      void run(const HEPUtils::Event* event)
      {
        // --- Missing momentum ---------------------------------------------
        double met = event->met();

        // --- Baseline objects (paper Sec. <object definitions>) ------------
        std::vector<const HEPUtils::Particle*> baselineElectrons;
        for (const HEPUtils::Particle* e : event->electrons())
          if (e->pT() > 10. && e->abseta() < 2.47) baselineElectrons.push_back(e);
        applyEfficiency(baselineElectrons, ATLAS::eff1DEl.at("PERF_2017_01_ID_Loose"));

        std::vector<const HEPUtils::Particle*> baselineMuons;
        for (const HEPUtils::Particle* m : event->muons())
          if (m->pT() > 10. && m->abseta() < 2.5) baselineMuons.push_back(m);

        std::vector<const HEPUtils::Jet*> baselineJets;
        for (const HEPUtils::Jet* j : event->jets("antikt_R04"))
          if (j->pT() > 20. && j->abseta() < 2.8) baselineJets.push_back(j);

        // --- Overlap removal (copy the paper's exact procedure) ------------
        // removeOverlap(baselineJets, baselineElectrons, 0.2);
        // removeOverlap(baselineElectrons, baselineJets, 0.4);

        // --- Signal objects -------------------------------------------------
        // ...

        // --- Cutflow + signal regions --------------------------------------
        BEGIN_PRESELECTION;
        // (baseline quality cuts here)
        END_PRESELECTION;

        size_t nJets = baselineJets.size();
        size_t nLeps = baselineElectrons.size() + baselineMuons.size();

        if (nLeps == 0) { LOG_CUT("SR-A", "SR-B") } else return;

        if (nJets >= 2 && met > 200.) FILL_SIGNAL_REGION("SR-A");
        if (nJets >= 4 && met > 300.) FILL_SIGNAL_REGION("SR-B");

        // FILL_HISTOGRAM_1D("met", met);
      }

      virtual void collect_results()
      {
        // Numbers from the paper's results table / HEPData — never invented
        COMMIT_SIGNAL_REGION("SR-A", /*obs*/ 0., /*bkg*/ 0., /*bkg_err*/ 0.)  // TBD
        COMMIT_SIGNAL_REGION("SR-B", /*obs*/ 0., /*bkg*/ 0., /*bkg_err*/ 0.)  // TBD

        // COMMIT_COVARIANCE_MATRIX({{1.0, 0.1}, {0.1, 1.0}})
        COMMIT_CUTFLOWS
        // COMMIT_HISTOGRAMS
      }

    protected:

      void analysis_specific_reset()
      {
        for (auto& pair : _counters) pair.second.reset();
      }

    };

    // Factory fn
    DEFINE_ANALYSIS_FACTORY(TEMPLATE)

  }
}
