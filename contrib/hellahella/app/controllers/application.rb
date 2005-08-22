# The filters added to this controller will be run for all controllers in the application.
# Likewise will all the methods added be available for all controllers.
class ApplicationController < ActionController::Base
  
  private
  def authorize
    unless session[:user_id]
      flash[:notice] = "Please log in"
      session[:jumpto] = request.parameters
      redirect_to :controller => "login", :action => "login"
    end
  end
  
  def defaults
    @username = 'joe'
    @password = 'honker'
    @hnzb_server = '192.168.2.2'
    @hnzb_password = 'changeme'
    @hnzb_port = 8760
  end
end